from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import (
    BearerAuthBackend,
    RequireAuthMiddleware,
)
from mcp.server.auth.provider import ProviderTokenVerifier
from mcp.server.auth.routes import (
    create_auth_routes,
    create_protected_resource_routes,
)
from mcp.server.auth.settings import (
    ClientRegistrationOptions,
    RevocationOptions,
)
from pydantic import AnyHttpUrl
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.routing import Route

from librarian.api.core.oauth.auth_server.provider import LibrarianOAuthProvider
from librarian.api.db import attach_db_connection_pool
from librarian.api.endpoints.auth.me import router as auth_me_router
from librarian.api.endpoints.data.files import router as data_files_router
from librarian.api.endpoints.data.query import router as data_query_router
from librarian.api.endpoints.data.tree import router as data_tree_router
from librarian.api.endpoints.health import router as health_router
from librarian.api.endpoints.oauth.google import router as oauth_google_router
from librarian.api.endpoints.oauth.mcp.consent import router as oauth_mcp_router
from librarian.api.endpoints.settings.catalog import router as settings_catalog_router
from librarian.api.endpoints.settings.me import router as settings_me_router
from librarian.api.endpoints.settings.tokens import router as settings_tokens_router
from librarian.api.endpoints.settings.usage import router as settings_usage_router
from librarian.api.http import attach_http_client
from librarian.api.mcp import attach_deps, build_asgi, detach_deps, mcp
from librarian.api.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with (
        attach_db_connection_pool(app),
        attach_http_client(app),
    ):
        # The MCP tool reuses the same pool / HTTP client as the rest of
        # the API. Per-call user identity now comes from the SDK's bearer
        # middleware (LibrarianAccessToken.user_id), so MCPDeps no longer
        # carries that — it only holds the shared infra handles.
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
    app.include_router(oauth_mcp_router)
    app.include_router(auth_me_router)
    app.include_router(data_files_router)
    app.include_router(data_tree_router)
    app.include_router(data_query_router)
    app.include_router(settings_catalog_router)
    app.include_router(settings_me_router)
    app.include_router(settings_tokens_router)
    app.include_router(settings_usage_router)

    # OAuth authorization server — `/.well-known/oauth-authorization-server`,
    # `/authorize`, `/token`, `/register`, `/revoke`. The SDK builds these
    # routes from the provider; we just append them to the FastAPI router.
    # The provider reads its database pool off `app.state` on demand, so
    # building it here (before the lifespan attaches the pool) is fine.
    provider = LibrarianOAuthProvider(app=app, settings=settings.oauth_as)
    auth_routes = create_auth_routes(
        provider=provider,
        issuer_url=AnyHttpUrl(str(settings.oauth_as.public_base_url)),
        # Open dynamic client registration — see 13.mcp_oauth.md for the
        # rationale. Without this, claude.ai cannot enrol itself when a
        # user pastes the MCP URL.
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=[settings.oauth_as.mcp_scope],
            default_scopes=[settings.oauth_as.mcp_scope],
        ),
        revocation_options=RevocationOptions(enabled=True),
    )
    app.router.routes.extend(auth_routes)

    # RFC 9728 protected-resource metadata. Lives at
    # /.well-known/oauth-protected-resource/mcp and tells discoverers
    # which authorization server protects /mcp.
    resource_routes = create_protected_resource_routes(
        resource_url=settings.oauth_as.mcp_resource_url,
        authorization_servers=[
            AnyHttpUrl(str(settings.oauth_as.public_base_url)),
        ],
        scopes_supported=[settings.oauth_as.mcp_scope],
    )
    app.router.routes.extend(resource_routes)

    # MCP Streamable-HTTP endpoint. The ASGI handles POST (JSON-RPC),
    # GET (server→client SSE stream), and DELETE (session terminate) on
    # this exact path — there is no sub-routing inside.
    #
    # We register the same ASGI as two Starlette `Route`s (at `/mcp` and
    # `/mcp/`) rather than `app.mount("/mcp", ...)`. Mount uses an inner
    # `/mcp/{path:path}` regex and relies on the Router's trailing-slash
    # redirect to bridge `/mcp` → `/mcp/` — but that redirect loses
    # request bodies on some HTTP clients (the spec preserves them for
    # 307, but the chain isn't always faithful), and claude.ai
    # normalises to `/mcp` (no trailing slash) before its first call.
    # Two exact-match Routes sidestep the redirect entirely.
    #
    # The ASGI is wrapped with three SDK middlewares before being mounted.
    # Wrapping order matters: outermost runs first on the incoming
    # request, so the chain runs Authentication → RequireAuth → AuthContext
    # → inner ASGI.
    #
    #   - AuthenticationMiddleware + BearerAuthBackend reads the Bearer
    #     token via the provider's load_access_token, populates
    #     `scope["user"]` with an AuthenticatedUser carrying the
    #     LibrarianAccessToken (which includes the resolved user_id).
    #   - RequireAuthMiddleware refuses requests that don't carry the
    #     mcp_scope, replying with 401 + WWW-Authenticate pointing at
    #     the protected-resource metadata URL.
    #   - AuthContextMiddleware copies the authenticated user into a
    #     contextvar so the MCP tool can read the user via
    #     `get_access_token()` without threading the request through.
    mcp_asgi = build_asgi()
    mcp_asgi = AuthContextMiddleware(mcp_asgi)
    mcp_asgi = RequireAuthMiddleware(
        mcp_asgi,
        required_scopes=[settings.oauth_as.mcp_scope],
        resource_metadata_url=settings.oauth_as.mcp_resource_metadata_url,
    )
    mcp_asgi = AuthenticationMiddleware(
        mcp_asgi,
        backend=BearerAuthBackend(ProviderTokenVerifier(provider)),  # type: ignore[arg-type]
    )
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
