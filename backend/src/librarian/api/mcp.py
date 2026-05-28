"""MCP server: exposes the retrieval pipeline as a single Streamable-HTTP
tool, intended to be mounted on the FastAPI app at `/mcp`.

The same `service.retrieval.run.run_retrieval` driver that powers the
internal `/data/query` endpoints is reused here — the only thing that
changes is *how* the in-flight events are surfaced. The SSE endpoint
formats them as `text/event-stream` frames; the MCP tool turns them
into `ctx.report_progress(...)` notifications so the calling LLM sees
the agent's tree walk land on the tool card under the spinner. The
final answer arrives as the tool result.

Per-call user identity arrives via the SDK's OAuth flow: the bearer
middleware (wired in `app.py`) populates a contextvar with the active
`LibrarianAccessToken`, which the tool reads via `get_access_token()`.
"""

import logging
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientSession
from asyncpg import Pool
from fastapi import HTTPException
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.server import StreamableHTTPASGIApp
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field

from librarian.api.core.oauth.auth_server.provider import LibrarianAccessToken
from librarian.service.retrieval.events import (
    BlobResult,
    ExpandEvent,
    FetchEvent,
    QueryEvent,
    TermsEvent,
)
from librarian.service.retrieval.preflight import preflight_query
from librarian.service.retrieval.run import run_retrieval
from librarian.service.retrieval.tools import BudgetExceededError

logger = logging.getLogger(__name__)


@dataclass
class MCPDeps:
    """Pool + HTTP client the MCP tool needs to run a retrieval. Held
    module-level (populated from the FastAPI lifespan) because a tool
    callback running inside the mounted Starlette sub-app has no clean
    handle on the parent FastAPI app's `state`. The per-user identity
    moved out of here — it now comes from the SDK's OAuth access token
    on every call (see `current_user_id`).
    """

    pool: Pool
    http: ClientSession


mcp_deps: MCPDeps | None = None


def attach_deps(pool: Pool, http: ClientSession) -> None:
    global mcp_deps
    mcp_deps = MCPDeps(pool=pool, http=http)


def detach_deps() -> None:
    global mcp_deps
    mcp_deps = None


def get_deps() -> MCPDeps:
    if mcp_deps is None:
        raise RuntimeError(
            "MCP deps are not attached. Check the FastAPI lifespan wiring."
        )
    return mcp_deps


def current_user_id() -> int:
    """Read the authenticated user_id off the active OAuth access token.

    The bearer middleware in `app.py` runs ahead of every /mcp request
    and populates a contextvar via `AuthContextMiddleware`; this helper
    is the bridge to that contextvar. Inside a tool callback there is
    no clean way to reach the request scope otherwise (Context only
    exposes session-level state), so we go through the SDK's official
    accessor.
    """
    access_token = get_access_token()
    if access_token is None or not isinstance(access_token, LibrarianAccessToken):
        # Should not happen under normal use: RequireAuthMiddleware would
        # have already rejected an unauthenticated request with 401. If
        # we reach the tool body without a LibrarianAccessToken,
        # something has been mis-wired upstream.
        raise RuntimeError(
            "MCP tool invoked without an authenticated LibrarianAccessToken."
        )
    return access_token.user_id


class MCPQueryResult(BaseModel):
    """What the MCP tool returns to the calling LLM. Strict subset of the
    internal `RetrievalResult`: drops `visited_node_ids` and `steps`
    (internal debugging signal — not useful to the caller), keeps the
    rationale so the LLM understands *why* the agent picked these blobs
    on top of *what* they contain.
    """

    rationale: str = Field(
        description=(
            "Short note from the retrieval agent explaining why these blobs "
            "were chosen as the best matches for the question."
        )
    )
    effective_search_terms: str = Field(
        description=(
            "The distilled search-terms string that was actually embedded "
            "and used to score document similarity. When `search_terms` was "
            "omitted from the call, this is the LLM-extracted distillation "
            "of `question` — useful to confirm what the agent searched for."
        )
    )
    blobs: list[BlobResult] = Field(
        description=(
            "Selected document fragments, in priority order. Each carries "
            "the source file path, byte/page range, a structured abstract, "
            "and the full plaintext content of the fragment."
        )
    )


# Stateless mode: the MCP retrieval has no notion of a multi-request session
# (no `initialize` state we want to keep). Each call spins up a fresh
# transport so concurrent /mcp callers don't share session state.
#
# DNS rebinding protection is disabled explicitly. FastMCP auto-enables it
# for localhost hosts, which is the right default when the server is
# directly reachable by a browser; in our deployment shape the MCP endpoint
# sits behind a trusted reverse proxy on a remote, and the Host header the
# inner server sees is whatever nginx forwards (the public hostname), not
# localhost. The proxy is the trust boundary, not this middleware.
mcp = FastMCP(
    name="librarian",
    instructions=(
        "Tools to retrieve the most relevant fragments from the user's "
        "personal document library, organised as an LLM-summarised "
        "abstraction tree. Use `query_library` to answer questions about "
        "the user's documents."
    ),
    stateless_http=True,
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)


def event_summary(event: QueryEvent) -> str | None:
    """Render a `QueryEvent` as a one-line progress message.

    Mirrors what the FE shows from the SSE stream but in flat text — the
    calling LLM benefits from compact, scannable progress lines, not from
    the structured payload. Used as the `message` argument of
    `ctx.report_progress`. Returns `None` for events that don't need to
    be surfaced (DoneEvent: its payload becomes the tool result; ErrorEvent
    isn't emitted on the success path).
    """
    if isinstance(event, TermsEvent):
        source = "extracted from question" if event.extracted else "as provided"
        return f"Searched for: {event.effective_search_terms!r} ({source})."
    if isinstance(event, ExpandEvent):
        node_ids = ", ".join(str(n) for n in event.requested_node_ids)
        return (
            f"Step {event.step}/{event.budget}: expanded "
            f"{len(event.requested_node_ids)} node(s) [{node_ids}]."
        )
    if isinstance(event, FetchEvent):
        blob_ids = ", ".join(str(b) for b in event.blob_ids)
        return f"Peeked at {len(event.blob_ids)} blob(s) [{blob_ids}]."
    return None


@mcp.tool(
    name="query_library",
    title="Search the user's document library",
    description=(
        "Answer a free-form question by walking the user's personal document "
        "library and returning the most relevant fragments. The library is "
        "indexed as a tree of LLM-generated abstracts; a retrieval agent "
        "descends the tree, peeks at candidate fragments, and selects up to "
        "a handful of best matches.\n\n"
        "Arguments:\n"
        "  - `question`: the user's natural-language question. This is what "
        "the agent reads and reasons about; phrase it as the user would.\n"
        "  - `search_terms` (optional): a sharper string to embed for "
        "similarity scoring at each descent step. Pass this when the "
        "question is long, conversational, or wraps the actual topic in "
        "framing that wouldn't appear in document text (e.g. 'I'm trying to "
        "remember that paper I read last month about X' → "
        "search_terms='X'). Leave it out for terse, on-topic questions; "
        "the server will distill terms from the question automatically.\n\n"
        "Progress is reported via log notifications as the agent descends "
        "the tree, peeks at blobs, and finalises its selection. The final "
        "result contains the agent's rationale plus the selected fragments "
        "with their abstracts and plaintext contents."
    ),
)
async def query_library(
    question: str,
    search_terms: str | None,
    ctx: Context,  # type: ignore[type-arg]
) -> MCPQueryResult:
    deps = get_deps()
    user_id = current_user_id()

    # Progress state, updated as the agent descends. Only ExpandEvent carries
    # the step/budget pair; TermsEvent and FetchEvent reuse the last known
    # values so the bar (in clients that render one) moves monotonically while
    # the `message` keeps reflecting what the agent is doing right now. Both
    # `progress` and `total` are floats per the MCP spec.
    progress = 0.0
    total: float | None = None

    async def emit(event: QueryEvent) -> None:
        nonlocal progress, total
        if isinstance(event, ExpandEvent):
            progress = float(event.step)
            total = float(event.budget)
        message = event_summary(event)
        if message is not None:
            # `report_progress` is a silent no-op if the client did not send a
            # `progressToken` with the call. claude.ai does send one for tool
            # invocations, so the message lands on the tool card; other
            # clients that don't will see only the final tool result.
            await ctx.report_progress(progress=progress, total=total, message=message)

    async with deps.pool.acquire() as conn:
        try:
            preflight = await preflight_query(
                deps.http, conn, user_id, question, search_terms
            )
            result = await run_retrieval(
                conn, deps.http, user_id, question, preflight, emit
            )
        except HTTPException as exc:
            # preflight + setup_query both raise HTTPException for the
            # readiness / auth / validation gates. The MCP wire format has
            # no notion of HTTP status codes; flatten to a tool error whose
            # message preserves the detail the FastAPI client would have
            # seen.
            raise ValueError(
                f"retrieval failed ({exc.status_code}): {exc.detail}"
            ) from exc
        except BudgetExceededError as exc:
            raise ValueError(f"retrieval budget exhausted: {exc}") from exc

    return MCPQueryResult(
        rationale=result.rationale,
        effective_search_terms=result.effective_search_terms,
        blobs=result.blobs,
    )


def build_asgi() -> Any:
    """Initialise the MCP session manager (lazy inside FastMCP) and return a
    raw ASGI app that delegates to it. The caller mounts this on the FastAPI
    app at `/mcp`; the session manager itself is run from the FastAPI
    lifespan.

    Returns a raw `StreamableHTTPASGIApp` rather than the Starlette wrapper
    that `mcp.streamable_http_app()` builds — we don't need the wrapper's
    extra routing layer once we're mounting under FastAPI, and skipping it
    sidesteps a path-stripping mismatch between FastAPI's mount and
    Starlette's inner Route at `streamable_http_path`.
    """
    # Side effect: lazily creates `mcp._session_manager`.
    mcp.streamable_http_app()
    return StreamableHTTPASGIApp(mcp.session_manager)
