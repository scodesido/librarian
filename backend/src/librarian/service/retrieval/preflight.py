import logging
from dataclasses import dataclass

import numpy as np
from aiohttp import ClientSession
from asyncpg.pool import PoolConnectionProxy
from fastapi import HTTPException
from numpy.typing import NDArray

from librarian.api.settings import settings
from librarian.db.readiness import PipelineCounts, count_user_pipeline
from librarian.db.tree_children import fetch_node_row
from librarian.service.credentials import UserCredentials
from librarian.service.embedder import build_embedder
from librarian.service.retrieval.embed import embed_search_terms
from librarian.service.retrieval.extract import (
    build_extractor_agent,
    extract_search_terms,
)
from librarian.service.usage import TokenUsage, record_usage

logger = logging.getLogger(__name__)


@dataclass
class QueryPreflight:
    """Result of preflight_query: the L2-normalised embedding of the
    effective search string, the string itself, and a flag indicating
    whether it came from the pre-flight extraction step (True) or from
    an explicit body.search_terms / the question verbatim (False).
    """

    search_embedding: NDArray[np.float32]
    effective_search_terms: str
    extracted: bool


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
    http: ClientSession,
    conn: PoolConnectionProxy,
    user_id: int,
    question: str,
    search_terms: str | None,
    creds: UserCredentials,
) -> QueryPreflight:
    """Pre-flight gate: validates question/search_terms length and tree
    readiness, derives the effective search string (either an explicit
    `search_terms`, or an LLM-extracted distillation of the question),
    and embeds it with the same embedder used to index the library.

    Embedding (and extraction) happen here rather than inside the agent
    so that both LLM and embedder failures surface as proper HTTP errors
    instead of mid-stream `error` events on a 200 — same shape the
    readiness gate already has.

    Raises HTTPException with the right status code so all callers
    surface it as a normal HTTP error.
    """
    if len(question) > settings.query.question_max_chars:
        raise HTTPException(
            status_code=422,
            detail=(
                f"question is {len(question)} chars; max is "
                f"{settings.query.question_max_chars}"
            ),
        )
    if (
        search_terms is not None
        and len(search_terms) > settings.query.question_max_chars
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"search_terms is {len(search_terms)} chars; max is "
                f"{settings.query.question_max_chars}"
            ),
        )
    counts = await count_user_pipeline(conn, user_id)
    assert_tree_ready(counts)
    root = await fetch_node_row(conn, user_id, None)
    if root is None:
        raise HTTPException(status_code=404, detail="No tree built yet.")

    if search_terms is not None:
        effective = search_terms
        extracted = False
    else:
        extractor = build_extractor_agent(settings.query, creds.extract_llm)
        result, extract_usage = await extract_search_terms(extractor, question)
        effective = result.terms
        extracted = True
        await record_usage(
            conn,
            user_id,
            "extract_search_terms",
            creds.extract_llm.model,
            extract_usage,
        )
        logger.info(
            "retrieval: user %s extracted search terms %r (rationale: %s)",
            user_id,
            effective,
            result.rationale,
        )

    embedder = build_embedder(
        model=creds.embedding.model,
        api_token=creds.embedding.api_token,
        ollama_host=creds.embedding.ollama_host,
        dimensions=settings.embeddings.dimensions,
    )
    search_embedding, embed_input_tokens = await embed_search_terms(
        http,
        embedder,
        effective,
        settings.embeddings.chunk_chars,
        settings.embeddings.chunk_chars_max,
    )
    await record_usage(
        conn,
        user_id,
        "embed_query",
        creds.embedding.model,
        TokenUsage(input_tokens=embed_input_tokens, output_tokens=0),
    )
    return QueryPreflight(
        search_embedding=search_embedding,
        effective_search_terms=effective,
        extracted=extracted,
    )
