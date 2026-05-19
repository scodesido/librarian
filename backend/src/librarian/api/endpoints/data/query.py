import asyncio
import logging
from typing import AsyncIterator

from aiohttp import ClientSession
from asyncpg import Pool
from asyncpg.pool import PoolConnectionProxy
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from librarian.api.core.auth.user import CurrentUser
from librarian.api.db import DbConnection
from librarian.api.http import HttpClient
from librarian.api.settings import settings
from librarian.common.oauth.google.access import NoGoogleAuthError
from librarian.db.readiness import PipelineCounts, count_user_pipeline
from librarian.db.tree_children import (
    InvalidBlobRefError,
    fetch_node_row,
    parse_blob_ref,
)
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
    ErrorEvent,
    QueryEvent,
)
from librarian.service.retrieval.providers import build_blob_provider
from librarian.service.retrieval.tools import (
    BudgetExceededError,
    resolve_blob_results,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data/query")


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)


class QueryResponse(BaseModel):
    blobs: list[BlobResult]
    visited_node_ids: list[int]
    steps: int
    rationale: str


def assert_tree_ready(counts: PipelineCounts) -> None:
    """The agent assumes the tree is fully built (every node has an abstract).
    If anything is still cooking, return 409 with the specific gap so the UI
    can show a useful message.
    """
    if counts.files_total == 0:
        raise HTTPException(status_code=409, detail="No files synced yet.")
    if counts.files_ready < counts.files_total:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Files still extracting "
                f"({counts.files_ready}/{counts.files_total}). "
                "Wait for blob_extractor to finish."
            ),
        )
    if counts.blobs_total == 0:
        raise HTTPException(
            status_code=409,
            detail="No blobs available (all synced files are of type OTHER).",
        )
    if counts.blobs_in_tree < counts.blobs_total:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Tree still building "
                f"({counts.blobs_in_tree}/{counts.blobs_total} blobs attached). "
                "Wait for tree_builder to finish."
            ),
        )
    if counts.nodes_total == 0 or counts.nodes_abstracted < counts.nodes_total:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Abstracts still computing "
                f"({counts.nodes_abstracted}/{counts.nodes_total} nodes). "
                "Wait for node_extractor to finish."
            ),
        )


async def preflight_query(
    conn: PoolConnectionProxy, user_id: int, question: str
) -> None:
    """Pre-flight gate: validates question length and tree readiness. Raises
    HTTPException with the right status code so both endpoints surface it
    as a normal HTTP error (rather than buried inside a 200 SSE stream).
    """
    if len(question) > settings.query.question_max_chars:
        raise HTTPException(
            status_code=422,
            detail=(
                f"question is {len(question)} chars; max is "
                f"{settings.query.question_max_chars}"
            ),
        )
    counts = await count_user_pipeline(conn, user_id)
    assert_tree_ready(counts)
    root = await fetch_node_row(conn, user_id, None)
    if root is None:
        raise HTTPException(status_code=404, detail="No tree built yet.")


async def setup_query(
    conn: PoolConnectionProxy,
    http: ClientSession,
    user_id: int,
    emit: "asyncio.Queue[QueryEvent | None] | None",
) -> tuple[QueryDeps, str]:
    """Post-preflight per-request state assembly: root lookup, budget, seed,
    provider, deps. Assumes preflight_query has already passed.
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
    seed = await build_seed_context(conn, user_id, root)
    instructions = build_instructions(settings.query, budget, seed)

    queue_emit = None
    if emit is not None:

        async def push(ev: QueryEvent) -> None:
            await emit.put(ev)

        queue_emit = push

    deps = QueryDeps(
        conn=conn,
        http=http,
        user_id=user_id,
        settings=settings.query,
        provider=provider,
        budget=budget,
        emit=queue_emit,
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


@router.post("", response_model=QueryResponse)
async def query(
    user_id: CurrentUser,
    conn: DbConnection,
    http: HttpClient,
    body: QueryRequest,
) -> QueryResponse:
    """Non-streaming retrieval. Runs the agent to completion, then resolves
    the chosen blob_ids into a full response. Use `POST /data/query/stream`
    for incremental progress.
    """
    await preflight_query(conn, user_id, body.question)
    deps, instructions = await setup_query(conn, http, user_id, None)
    agent = build_query_agent(settings.query, instructions)
    try:
        result = await agent.run(body.question, deps=deps)
    except BudgetExceededError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Descent budget exhausted after {deps.step_count} steps "
                f"(budget {deps.budget}). {exc}"
            ),
        ) from exc
    final = result.output
    blob_ids = cap_blob_ids(
        parse_final_blob_refs(final.blob_refs), settings.query.max_returned_blobs
    )
    blobs = await resolve_blob_results(deps, blob_ids)
    return QueryResponse(
        blobs=blobs,
        visited_node_ids=deps.visited_node_ids,
        steps=deps.step_count,
        rationale=final.rationale,
    )


async def query_event_stream(
    pool: Pool,
    http: ClientSession,
    user_id: int,
    question: str,
) -> AsyncIterator[bytes]:
    """Run the agent against its own pool connection (not the request-scoped
    one — the StreamingResponse generator outlives the request handler) and
    emit SSE events as the tools fire. Final result comes through as one
    `done` event; errors as one `error` event.
    """
    queue: asyncio.Queue[QueryEvent | None] = asyncio.Queue()
    async with pool.acquire() as conn:
        # Pre-flight ran in the route handler; this is just per-request state.
        # If a race deletes the tree between the two, setup_query raises
        # HTTPException(404), which we surface as an error event for symmetry
        # with other in-stream errors.
        try:
            deps, instructions = await setup_query(conn, http, user_id, queue)
        except HTTPException as exc:
            yield format_sse(ErrorEvent(detail=str(exc.detail)))
            return

        agent = build_query_agent(settings.query, instructions)

        async def run_agent() -> None:
            try:
                result = await agent.run(question, deps=deps)
                final = result.output
                blob_ids = cap_blob_ids(
                    parse_final_blob_refs(final.blob_refs),
                    settings.query.max_returned_blobs,
                )
                blobs = await resolve_blob_results(deps, blob_ids)
                await queue.put(
                    DoneEvent(
                        blobs=blobs,
                        visited_node_ids=list(deps.visited_node_ids),
                        steps=deps.step_count,
                        rationale=final.rationale,
                    )
                )
            except BudgetExceededError as exc:
                await queue.put(
                    ErrorEvent(
                        detail=(
                            f"Descent budget exhausted after {deps.step_count} "
                            f"steps (budget {deps.budget}). {exc}"
                        )
                    )
                )
            except Exception as exc:
                logger.exception("retrieval: stream agent run failed")
                await queue.put(ErrorEvent(detail=f"{type(exc).__name__}: {exc}"))
            finally:
                await queue.put(None)

        task = asyncio.create_task(run_agent())
        try:
            heartbeat = settings.query.sse_heartbeat_seconds
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=heartbeat)
                except asyncio.TimeoutError:
                    yield b": heartbeat\n\n"
                    continue
                if event is None:
                    return
                yield format_sse(event)
        finally:
            if not task.done():
                task.cancel()


def format_sse(event: QueryEvent) -> bytes:
    """SSE wire format: one `event:` line + one `data:` line + blank line."""
    payload = event.model_dump_json()
    return f"event: {event.kind}\ndata: {payload}\n\n".encode()


@router.post("/stream")
async def query_stream(
    user_id: CurrentUser,
    conn: DbConnection,
    request: Request,
    http: HttpClient,
    body: QueryRequest,
) -> StreamingResponse:
    """Streaming variant: same agent, same final answer, but progress events
    are emitted as the agent descends. Final answer arrives as the `done`
    event; errors as `error`. Heartbeat comments keep proxies from timing
    out idle connections.

    Pre-flight runs synchronously on the request-scoped connection so 422 /
    409 / 404 surface as proper HTTP status codes — only mid-stream failures
    end up as `error` events on a 200 response.
    """
    await preflight_query(conn, user_id, body.question)
    pool: Pool | None = request.app.state.db_connection_pool
    if pool is None:
        raise ValueError("No database connection pool available")
    return StreamingResponse(
        query_event_stream(pool, http, user_id, body.question),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
