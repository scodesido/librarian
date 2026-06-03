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

import json
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
from mcp.types import BlobResourceContents, EmbeddedResource, TextContent

from librarian.api.core.oauth.auth_server.provider import LibrarianAccessToken
from librarian.api.settings import settings
from librarian.service.credentials import (
    MissingTokenError,
    resolve_user_credentials,
)
from librarian.service.retrieval.events import (
    ProgressEvent,
    QueryEvent,
    TermsEvent,
)
from librarian.service.retrieval.preflight import preflight_query
from librarian.service.retrieval.run import RetrievalResult, run_retrieval
from librarian.service.retrieval.tools.errors import BudgetExceededError

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


ResultBlock = TextContent | EmbeddedResource


def result_to_blocks(result: RetrievalResult) -> list[ResultBlock]:
    """Render a RetrievalResult as MCP content blocks. Binary blob bytes can't
    live in MCP structured output, so we return content blocks uniformly in
    both modes: a leading text block with the rationale + effective terms, then
    per blob a pair — a text block with that blob's title/file_name/tags
    (JSON), followed by the content itself (a text block in text mode, or an
    embedded binary resource in binary mode). Keeping each blob's metadata
    adjacent to its bytes is the reason for interleaving rather than a header +
    a flat resource list.
    """
    blocks: list[ResultBlock] = [
        TextContent(
            type="text",
            text=json.dumps(
                {
                    "rationale": result.rationale,
                    "effective_search_terms": result.effective_search_terms,
                }
            ),
        )
    ]
    for index, blob in enumerate(result.blobs):
        blocks.append(
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "title": blob.title,
                        "file_name": blob.file_name,
                        "tags": blob.tags,
                    }
                ),
            )
        )
        if blob.encoding == "base64":
            blocks.append(
                EmbeddedResource(
                    type="resource",
                    resource=BlobResourceContents(
                        # Synthetic, non-identifying — we don't leak blob ids.
                        uri=f"librarian://result/{index}",
                        mimeType=blob.mime_type,
                        blob=blob.content,
                    ),
                )
            )
        else:
            blocks.append(TextContent(type="text", text=blob.content))
    return blocks


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


PROGRESS_VERBS: dict[str, str] = {
    "descend": "Descended into",
    "detail": "Inspected",
    "peek": "Peeked at",
    "file": "Listed file blobs",
}


def event_summary(event: QueryEvent) -> str | None:
    """Render a `QueryEvent` as a one-line progress message.

    Mirrors what the FE shows from the SSE stream but in flat text — the
    calling LLM benefits from compact, scannable progress lines, not from
    the structured payload. Used as the `message` argument of
    `ctx.report_progress`. Returns `None` for events that don't need to be
    surfaced (DoneEvent: its payload becomes the tool result; ErrorEvent isn't
    emitted on the success path).

    Only titles are shown — the same title+tags briefs the FE renders, minus
    any internal ids.
    """
    if isinstance(event, TermsEvent):
        source = "extracted from question" if event.extracted else "as provided"
        return f"Searched for: {event.effective_search_terms!r} ({source})."
    if isinstance(event, ProgressEvent):
        titles = ", ".join(b.title or "(untitled)" for b in event.items) or "—"
        if event.action == "descend" and event.step is not None:
            return f"Step {event.step}/{event.budget}: descended into {titles}."
        return f"{PROGRESS_VERBS[event.action]}: {titles}."
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
        "the server will distill terms from the question automatically.\n"
        "  - `binary` (optional, default false): when false, each fragment "
        "comes back as plaintext. When true, fragments come back as their "
        "original bytes — a PDF fragment as a PDF of its page range, a text "
        "fragment as raw bytes — embedded as binary resources. Use binary "
        "when layout/figures matter or you need the original file format.\n\n"
        "Progress is reported via log notifications as the agent descends "
        "the tree, inspects nodes and fragments, and finalises its selection. "
        "The result is the agent's rationale followed by the selected "
        "fragments, each with its title and tags and its content (text or an "
        "embedded binary resource)."
    ),
)
async def query_library(
    question: str,
    search_terms: str | None,
    ctx: Context,  # type: ignore[type-arg]
    binary: bool = False,
) -> list[ResultBlock]:
    deps = get_deps()
    user_id = current_user_id()

    # Progress state, updated as the agent descends. Only the `descend`
    # ProgressEvent carries the step/budget pair; other events reuse the last
    # known values so the bar (in clients that render one) moves monotonically
    # while the `message` keeps reflecting what the agent is doing right now.
    # Both `progress` and `total` are floats per the MCP spec.
    progress = 0.0
    total: float | None = None

    async def emit(event: QueryEvent) -> None:
        nonlocal progress, total
        if (
            isinstance(event, ProgressEvent)
            and event.step is not None
            and event.budget is not None
        ):
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
            creds = await resolve_user_credentials(
                conn,
                user_id,
                settings.model_catalog,
                settings.ollama,
                settings.user_tokens,
            )
            preflight = await preflight_query(
                deps.http, conn, user_id, question, search_terms, creds
            )
            result = await run_retrieval(
                conn, deps.http, user_id, question, preflight, creds, emit, binary
            )
        except MissingTokenError as exc:
            # MCP has no HTTP status; flatten to a tool error that names
            # the broken slot so the calling LLM can tell the user.
            raise ValueError(
                f"retrieval needs an API token for slot {exc.slot!r} "
                f"({exc.model!r}); please add it in Settings."
            ) from exc
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

    return result_to_blocks(result)


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
