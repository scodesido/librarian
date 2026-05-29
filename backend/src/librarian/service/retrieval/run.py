import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

import numpy as np
from aiohttp import ClientSession
from asyncpg.pool import PoolConnectionProxy
from fastapi import HTTPException
from numpy.typing import NDArray

from librarian.api.settings import settings
from librarian.common.oauth.google.access import NoGoogleAuthError
from librarian.db.tree_children import (
    InvalidBlobRefError,
    fetch_node_row,
    parse_blob_ref,
)
from librarian.service.credentials import UserCredentials
from librarian.service.retrieval.agent import (
    build_instructions,
    build_query_agent,
    build_seed_context,
    compute_budget,
)
from librarian.service.retrieval.deps import QueryDeps
from librarian.service.retrieval.events import (
    BlobResult,
    DoneEvent,
    QueryEvent,
    TermsEvent,
)
from librarian.service.retrieval.preflight import QueryPreflight
from librarian.service.retrieval.providers import build_blob_provider
from librarian.service.retrieval.tools import resolve_blob_results
from librarian.service.usage import agent_usage, record_usage

logger = logging.getLogger(__name__)

Emit = Callable[[QueryEvent], Awaitable[None]]


@dataclass
class RetrievalResult:
    """Final shape produced by run_retrieval. Mirrors DoneEvent's payload —
    the SSE wrapper emits a DoneEvent built from this, the JSON endpoint
    maps it onto QueryResponse, and the MCP tool projects a subset of it.
    """

    blobs: list[BlobResult]
    visited_node_ids: list[int]
    steps: int
    rationale: str
    effective_search_terms: str


async def setup_query(
    conn: PoolConnectionProxy,
    http: ClientSession,
    user_id: int,
    search_embedding: NDArray[np.float32],
    effective_search_terms: str,
    emit: Emit | None,
) -> tuple[QueryDeps, str]:
    """Post-preflight per-request state assembly: root lookup, budget, seed,
    provider, deps. Assumes preflight_query has already passed and produced
    the query embedding plus the effective search terms.
    """
    root = await fetch_node_row(conn, user_id, None)
    if root is None:
        # Race: the tree was deleted between preflight and here. Mirror the
        # preflight status code so the client sees one consistent shape.
        raise HTTPException(status_code=404, detail="No tree built yet.")

    # Pick the source via the first blob's owning file. With a single source
    # today (GDRIVE) this is effectively a constant; the lookup is here so a
    # future multi-source layout (e.g. one user, multiple connected accounts)
    # can fan out per source without changing the call shape.
    source_row = await conn.fetchrow(
        "SELECT source FROM data_files WHERE user_id = $1 LIMIT 1",
        user_id,
    )
    if source_row is None:
        raise HTTPException(status_code=409, detail="No files synced yet.")

    try:
        provider = await build_blob_provider(
            source_row["source"], conn, http, settings.google_oauth, user_id
        )
    except NoGoogleAuthError as exc:
        raise HTTPException(
            status_code=401, detail="User not connected to Google."
        ) from exc

    budget = compute_budget(root.height, settings.query.descent_budget_multiplier)
    seed = await build_seed_context(
        conn, user_id, root, search_embedding, effective_search_terms
    )
    instructions = build_instructions(settings.query, budget, seed)

    deps = QueryDeps(
        conn=conn,
        http=http,
        user_id=user_id,
        settings=settings.query,
        provider=provider,
        budget=budget,
        search_embedding=search_embedding,
        emit=emit,
    )
    return deps, instructions


def cap_blob_ids(blob_ids: list[int], cap: int) -> list[int]:
    """The agent is told the cap in its instructions; this is the
    defensive truncation in case it returns more anyway. Keeps prefix order
    (the agent is asked to return blob_ids in priority order).
    """
    if len(blob_ids) <= cap:
        return blob_ids
    logger.warning(
        "retrieval: agent returned %d blob_ids, truncating to %d",
        len(blob_ids),
        cap,
    )
    return blob_ids[:cap]


def parse_final_blob_refs(blob_refs: list[str]) -> list[int]:
    """Parse the agent's `FinalAnswer.blob_refs` (prefixed string refs) into
    raw blob_ids. A malformed ref here is an agent bug — the schema and the
    instructions both require 'b:NNN' — so it surfaces as a 502 rather than
    something the agent can recover from.
    """
    try:
        return [parse_blob_ref(r) for r in blob_refs]
    except InvalidBlobRefError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"agent returned an invalid blob ref in its final answer: {exc}",
        ) from exc


async def run_retrieval(
    conn: PoolConnectionProxy,
    http: ClientSession,
    user_id: int,
    question: str,
    preflight: QueryPreflight,
    creds: UserCredentials,
    emit: Emit | None,
) -> RetrievalResult:
    """Shared retrieval driver: set up per-request state on `conn`, run the
    agent to completion, resolve the chosen blob_ids into BlobResults. If
    `emit` is provided, the lifecycle events (TermsEvent first, ExpandEvent /
    FetchEvent during the agent loop, DoneEvent at the end) are pushed
    through it; otherwise the function is silent until it returns.

    Caller chooses the connection. The JSON endpoint passes the request-
    scoped conn directly; the SSE generator and the MCP tool acquire their
    own from the pool because they outlive the originating request handler.

    Errors are raised, not swallowed: BudgetExceededError, HTTPException
    from setup_query, agent exceptions. Each caller decides whether to
    surface them as HTTP errors or as ErrorEvent on an open stream.
    """
    deps, instructions = await setup_query(
        conn,
        http,
        user_id,
        preflight.search_embedding,
        preflight.effective_search_terms,
        emit,
    )
    if emit is not None:
        await emit(
            TermsEvent(
                effective_search_terms=preflight.effective_search_terms,
                extracted=preflight.extracted,
            )
        )

    agent = build_query_agent(settings.query, creds.retrieval_llm, instructions)
    result = await agent.run(question, deps=deps)
    await record_usage(
        conn,
        user_id,
        "retrieval",
        creds.retrieval_llm.model,
        agent_usage(result),
    )
    final = result.output
    blob_ids = cap_blob_ids(
        parse_final_blob_refs(final.blob_refs), settings.query.max_returned_blobs
    )
    blobs = await resolve_blob_results(deps, blob_ids)
    retrieval = RetrievalResult(
        blobs=blobs,
        visited_node_ids=list(deps.visited_node_ids),
        steps=deps.step_count,
        rationale=final.rationale,
        effective_search_terms=preflight.effective_search_terms,
    )
    if emit is not None:
        await emit(
            DoneEvent(
                blobs=retrieval.blobs,
                visited_node_ids=retrieval.visited_node_ids,
                steps=retrieval.steps,
                rationale=retrieval.rationale,
                effective_search_terms=retrieval.effective_search_terms,
            )
        )
    return retrieval
