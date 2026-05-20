from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.routing import Route

from librarian.api.db import attach_db_connection_pool
from librarian.api.endpoints.auth.me import router as auth_me_router
from librarian.api.endpoints.data.files import router as data_files_router
from librarian.api.endpoints.data.query import router as data_query_router
from librarian.api.endpoints.data.tree import router as data_tree_router
from librarian.api.endpoints.health import router as health_router
from librarian.api.endpoints.oauth.google import router as oauth_google_router
from librarian.api.http import attach_http_client
from librarian.api.mcp import attach_deps, build_asgi, detach_deps, mcp
from librarian.api.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with (
        attach_db_connection_pool(app),
        attach_http_client(app),
    ):
        # The MCP server reuses the same pool and HTTP client as the rest
        # of the API. Wire them in before the session manager starts so the
        # first tool call sees fully-initialised deps.
        attach_deps(app.state.db_connection_pool, app.state.http_client)
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            detach_deps()


def create() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    app.include_router(health_router)
    app.include_router(oauth_google_router)
    app.include_router(auth_me_router)
    app.include_router(data_files_router)
    app.include_router(data_tree_router)
    app.include_router(data_query_router)

    # MCP Streamable-HTTP endpoint. The ASGI handles POST (JSON-RPC),
    # GET (server→client SSE stream), and DELETE (session terminate) on
    # this exact path — there is no sub-routing inside.
    #
    # We register the same ASGI as two Starlette `Route`s (at `/mcp` and
    # `/mcp/`) rather than a single `app.mount("/mcp", ...)`. Mount uses
    # an inner `/mcp/{path:path}` regex and relies on the Router's
    # trailing-slash redirect to bridge `/mcp` → `/mcp/`, which (a) only
    # works correctly when uvicorn's `root_path` matches the deployed
    # prefix, and (b) loses request bodies on some HTTP clients that
    # convert the redirected POST to GET. Two exact-match Routes sidestep
    # both problems: claude.ai's URL normalisation to `/mcp` (no trailing
    # slash) hits the first Route directly, no redirect involved.
    mcp_asgi = build_asgi()
    app.router.routes.append(Route("/mcp", endpoint=mcp_asgi))
    app.router.routes.append(Route("/mcp/", endpoint=mcp_asgi))

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api.cors_origins,
        allow_headers=settings.api.cors_headers,
        allow_methods=settings.api.cors_methods,
        allow_credentials=True,
    )

    return app
