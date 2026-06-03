import asyncio
import logging
from typing import AsyncIterator, Literal

from aiohttp import ClientSession
from asyncpg import Pool
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from librarian.api.core.auth.user import CurrentUser
from librarian.api.db import DbConnection
from librarian.api.http import HttpClient
from librarian.api.settings import settings
from librarian.service.credentials import (
    MissingTokenError,
    UserCredentials,
    resolve_user_credentials,
)
from librarian.service.retrieval.events import (
    ErrorEvent,
    QueryEvent,
    ResultBlob,
)
from librarian.service.retrieval.preflight import (
    QueryPreflight,
    preflight_query,
)
from librarian.service.retrieval.run import run_retrieval
from librarian.service.retrieval.tools.errors import BudgetExceededError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data/query")


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    # Optional override for the text that gets embedded and used to score
    # sibling children at each list_children step. When None, the question
    # itself is embedded — useful for short, well-framed questions. When
    # set, the agent still answers the `question` but the similarity hint
    # follows `search_terms`, which is useful when the question is long-
    # winded or full of conversational framing and the user can name the
    # underlying topic more directly.
    search_terms: str | None = Field(default=None, min_length=1)
    # How the selected blobs' contents come back. "text" (default) returns
    # plaintext; "binary" returns the original bytes (PDF page range as PDF,
    # text slice as bytes) base64-encoded. The webapp always uses "text".
    content_format: Literal["text", "binary"] = "text"


class QueryResponse(BaseModel):
    rationale: str
    # Echoes the search-terms string used for similarity scoring. Mirrors
    # the SSE `terms` event so JSON callers have access to the same info
    # without consuming the stream.
    effective_search_terms: str
    blobs: list[ResultBlob]


def missing_token_http(exc: MissingTokenError) -> HTTPException:
    """Map MissingTokenError -> 409 with a message naming the broken slot.
    409 mirrors the readiness-gate shape ("user's state isn't ready for
    this request"), so the FE can render the same kind of inline
    actionable message it already shows for tree-not-built.
    """
    return HTTPException(
        status_code=409,
        detail=(
            f"Slot {exc.slot!r} is set to {exc.model!r}, which needs an API "
            "token. Visit Settings to add it."
        ),
    )


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
    try:
        creds = await resolve_user_credentials(
            conn,
            user_id,
            settings.model_catalog,
            settings.ollama,
            settings.user_tokens,
        )
    except MissingTokenError as exc:
        raise missing_token_http(exc) from exc
    preflight = await preflight_query(
        http, conn, user_id, body.question, body.search_terms, creds
    )
    try:
        result = await run_retrieval(
            conn,
            http,
            user_id,
            body.question,
            preflight,
            creds,
            emit=None,
            binary=body.content_format == "binary",
        )
    except BudgetExceededError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Descent budget exhausted. {exc}",
        ) from exc
    return QueryResponse(
        rationale=result.rationale,
        effective_search_terms=result.effective_search_terms,
        blobs=result.blobs,
    )


async def query_event_stream(
    pool: Pool,
    http: ClientSession,
    user_id: int,
    question: str,
    preflight: QueryPreflight,
    creds: UserCredentials,
    binary: bool,
) -> AsyncIterator[bytes]:
    """Run the agent against its own pool connection (not the request-scoped
    one — the StreamingResponse generator outlives the request handler) and
    emit SSE events as the tools fire. The shared `run_retrieval` driver
    handles TermsEvent / DoneEvent emission; expand/fetch come from the
    agent's tool calls via `deps.emit`.

    Errors mid-run surface as one `error` event (200 response, in-stream).
    Pre-flight ran in the route handler so HTTP-level failures don't end
    up here.
    """
    queue: asyncio.Queue[QueryEvent | None] = asyncio.Queue()
    async with pool.acquire() as conn:

        async def emit(ev: QueryEvent) -> None:
            await queue.put(ev)

        async def run() -> None:
            try:
                await run_retrieval(
                    conn, http, user_id, question, preflight, creds, emit, binary
                )
            except BudgetExceededError as exc:
                await queue.put(ErrorEvent(detail=f"Descent budget exhausted. {exc}"))
            except HTTPException as exc:
                # setup_query may raise this on a tree-deleted race. Surface
                # as an in-stream error event for symmetry with other
                # mid-stream failures.
                await queue.put(ErrorEvent(detail=str(exc.detail)))
            except Exception as exc:
                logger.exception("retrieval: stream agent run failed")
                await queue.put(ErrorEvent(detail=f"{type(exc).__name__}: {exc}"))
            finally:
                await queue.put(None)

        task = asyncio.create_task(run())
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
    try:
        creds = await resolve_user_credentials(
            conn,
            user_id,
            settings.model_catalog,
            settings.ollama,
            settings.user_tokens,
        )
    except MissingTokenError as exc:
        raise missing_token_http(exc) from exc
    preflight = await preflight_query(
        http, conn, user_id, body.question, body.search_terms, creds
    )
    pool: Pool | None = request.app.state.db_connection_pool
    if pool is None:
        raise ValueError("No database connection pool available")
    return StreamingResponse(
        query_event_stream(
            pool,
            http,
            user_id,
            body.question,
            preflight,
            creds,
            body.content_format == "binary",
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
