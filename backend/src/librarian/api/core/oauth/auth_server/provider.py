"""LibrarianOAuthProvider: the MCP SDK `OAuthAuthorizationServerProvider`
implementation that powers `/authorize`, `/token`, `/register`, `/revoke`.

User authentication is delegated: `authorize()` returns a URL pointing at
our `/oauth/mcp/continue` bridge endpoint, which either bounces the user
through the existing Google sign-in or jumps straight to the consent
screen. The bridge endpoint is also the only place that flips a grant
from `pending` to `granted` (by calling `OAuthAuthorizationGrants.grant`).

PKCE verification and redirect-URI matching are done by the SDK's /token
handler itself — we only persist the `code_challenge` and `redirect_uri`
so it can read them back.
"""

import secrets
from datetime import timedelta
from urllib.parse import urlencode

from asyncpg import Pool
from fastapi import FastAPI
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

from librarian.common.oauth.hash import token_hash
from librarian.common.settings.oauth_as import OAuthASSettings
from librarian.db.tables.oauth_access_tokens import OAuthAccessTokens
from librarian.db.tables.oauth_authorization_grants import (
    OAuthAuthorizationGrantModel,
    OAuthAuthorizationGrants,
)
from librarian.db.tables.oauth_clients import OAuthClientModel, OAuthClients
from librarian.db.tables.oauth_refresh_tokens import OAuthRefreshTokens


class LibrarianAccessToken(AccessToken):
    """SDK's `AccessToken` plus the Librarian user_id.

    The SDK's bearer middleware stores the AccessToken on
    `scope["user"].access_token` (and `auth_context_var` for retrieval
    inside tool callbacks via `get_access_token()`). Subclassing here is
    how we propagate the user identity from `load_access_token` all the
    way to the MCP tool without an extra DB lookup per call.
    """

    user_id: int


def to_client_information(model: OAuthClientModel) -> OAuthClientInformationFull:
    """Hydrate our row back into the SDK's client model. We don't store
    the optional RFC 7591 metadata fields (logo_uri, tos_uri, …); the SDK
    fills them in with None defaults.
    """
    return OAuthClientInformationFull(
        client_id=model.client_id,
        client_name=model.client_name,
        redirect_uris=[AnyUrl(uri) for uri in model.redirect_uris],
        scope=" ".join(model.scopes) if model.scopes else None,
        grant_types=list(model.grant_types),
        response_types=list(model.response_types),
        token_endpoint_auth_method=model.token_endpoint_auth_method,  # type: ignore[arg-type]
    )


class LibrarianOAuthProvider(
    OAuthAuthorizationServerProvider[
        AuthorizationCode, RefreshToken, LibrarianAccessToken
    ]
):
    """Reads the database pool off `app.state` on every call rather than
    capturing it at construction time. The provider is instantiated in
    `create()` so it can be wired into the SDK route builders, but the
    pool itself only exists from the lifespan onward; this indirection
    bridges that ordering.
    """

    def __init__(self, app: FastAPI, settings: OAuthASSettings) -> None:
        self.app = app
        self.settings = settings

    @property
    def pool(self) -> Pool:
        pool = self.app.state.db_connection_pool
        if pool is None:
            raise RuntimeError(
                "OAuth provider called before the database pool was attached."
            )
        return pool

    # --------------------------------------------------------------- clients

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with self.pool.acquire() as conn:
            model = await OAuthClients(conn).get(client_id)
        return to_client_information(model) if model is not None else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        # The SDK's /register handler has already minted a `client_id` and
        # validated redirect_uris is non-empty. We persist what we'll need
        # back: redirect_uris (for matching), client_name (for the consent
        # screen), and the protocol echoes. We don't store `client_secret`
        # because MCP clients register as public (auth_method='none') and
        # we don't authenticate them at /token.
        if client_info.client_id is None or client_info.redirect_uris is None:
            raise ValueError(
                "register_client called with missing client_id or redirect_uris"
            )
        async with self.pool.acquire() as conn:
            await OAuthClients(conn).register(
                client_id=client_info.client_id,
                client_name=client_info.client_name or "Unknown client",
                redirect_uris=[str(uri) for uri in client_info.redirect_uris],
                scopes=client_info.scope.split() if client_info.scope else [],
                grant_types=list(client_info.grant_types),
                response_types=list(client_info.response_types),
                token_endpoint_auth_method=(
                    client_info.token_endpoint_auth_method or "none"
                ),
            )

    # ------------------------------------------------------------- authorize

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        # Stash everything we'll need at /token-time (PKCE challenge,
        # redirect_uri, scopes, resource) keyed by a fresh nonce — which
        # *is* the authorization code that the MCP client will eventually
        # present to /token. Status starts as `pending`: the consent
        # endpoint is what flips it to `granted` and attaches a user.
        code = secrets.token_urlsafe(32)
        async with self.pool.acquire() as conn:
            await OAuthAuthorizationGrants(conn).create_pending(
                code=code,
                client_id=client.client_id or "",
                redirect_uri=str(params.redirect_uri),
                redirect_uri_explicit=params.redirect_uri_provided_explicitly,
                code_challenge=params.code_challenge,
                requested_scopes=params.scopes or [],
                resource=params.resource,
                client_state=params.state,
                ttl=timedelta(seconds=self.settings.authorization_grant_ttl_seconds),
            )
        # The user-facing entry point. The bridge endpoint reads `nonce`,
        # checks for a logged-in session, redirects through Google login
        # if missing, then renders the consent page. After consent, the
        # bridge composes the final redirect back to the MCP client.
        base = str(self.settings.public_base_url).rstrip("/")
        return f"{base}/oauth/mcp/continue?{urlencode({'nonce': code})}"

    # ------------------------------------------------------------------ code

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        async with self.pool.acquire() as conn:
            grant = await OAuthAuthorizationGrants(conn).load_granted(
                code=authorization_code,
                client_id=client.client_id or "",
            )
        if grant is None:
            return None
        return _to_authorization_code(grant)

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        # The /token handler has already verified PKCE and redirect_uri at
        # this point. We just need to load the granted row, mint the
        # tokens, and mark the code consumed.
        async with self.pool.acquire() as conn:
            grants = OAuthAuthorizationGrants(conn)
            grant = await grants.load_granted(
                code=authorization_code.code,
                client_id=client.client_id or "",
            )
            if grant is None or grant.user_id is None:
                # Should not happen — the SDK only calls exchange after a
                # successful load, but be defensive: a concurrent /token
                # call could have raced us to consume.
                raise ValueError("authorization code is no longer valid")
            access_token, refresh_token, expires_in = await self._issue_token_pair(
                conn,
                user_id=grant.user_id,
                client_id=grant.client_id,
                scopes=list(grant.requested_scopes),
                resource=grant.resource,
            )
            await grants.consume(authorization_code.code)
        scope_str = " ".join(grant.requested_scopes) if grant.requested_scopes else None
        return OAuthToken(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            scope=scope_str,
        )

    # --------------------------------------------------------------- refresh

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        async with self.pool.acquire() as conn:
            row = await OAuthRefreshTokens(conn).load(token_hash(refresh_token))
        if row is None or row.client_id != (client.client_id or ""):
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=row.client_id,
            scopes=list(row.scopes),
            expires_at=int(row.expires_at.timestamp()),
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        # Rotate the refresh token on every use — limits the damage if a
        # token leaks at rest somewhere. Narrowing scopes is allowed (the
        # caller can request a subset of the refresh token's scopes);
        # widening is rejected by the SDK before this method is called.
        async with self.pool.acquire() as conn:
            refresh_tokens = OAuthRefreshTokens(conn)
            old_row = await refresh_tokens.load(token_hash(refresh_token.token))
            if old_row is None:
                raise ValueError("refresh token is no longer valid")
            effective_scopes = scopes if scopes else list(old_row.scopes)
            await refresh_tokens.revoke(old_row.token_hash)
            access_token, new_refresh_token, expires_in = await self._issue_token_pair(
                conn,
                user_id=old_row.user_id,
                client_id=old_row.client_id,
                scopes=effective_scopes,
                resource=old_row.resource,
            )
        return OAuthToken(
            access_token=access_token,
            refresh_token=new_refresh_token,
            expires_in=expires_in,
            scope=" ".join(effective_scopes) if effective_scopes else None,
        )

    # ---------------------------------------------------------- access token

    async def load_access_token(self, token: str) -> LibrarianAccessToken | None:
        async with self.pool.acquire() as conn:
            row = await OAuthAccessTokens(conn).load(token_hash(token))
        if row is None:
            return None
        return LibrarianAccessToken(
            token=token,
            client_id=row.client_id,
            scopes=list(row.scopes),
            expires_at=int(row.expires_at.timestamp()),
            resource=row.resource,
            user_id=row.user_id,
        )

    # ----------------------------------------------------------------- revoke

    async def revoke_token(self, token: LibrarianAccessToken | RefreshToken) -> None:
        # We don't know from the token type alone which table it's in —
        # the SDK can hand either to us. Try both: a delete on a missing
        # row is a no-op, and the cost is one extra round-trip.
        digest = token_hash(token.token)
        async with self.pool.acquire() as conn:
            await OAuthAccessTokens(conn).revoke(digest)
            await OAuthRefreshTokens(conn).revoke(digest)

    # --------------------------------------------------------------- helpers

    async def _issue_token_pair(
        self,
        conn,  # type: ignore[no-untyped-def]
        user_id: int,
        client_id: str,
        scopes: list[str],
        resource: str | None,
    ) -> tuple[str, str, int]:
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        access_ttl = timedelta(seconds=self.settings.access_token_ttl_seconds)
        refresh_ttl = timedelta(seconds=self.settings.refresh_token_ttl_seconds)
        await OAuthAccessTokens(conn).create(
            token_hash=token_hash(access),
            user_id=user_id,
            client_id=client_id,
            scopes=scopes,
            resource=resource,
            ttl=access_ttl,
        )
        await OAuthRefreshTokens(conn).create(
            token_hash=token_hash(refresh),
            user_id=user_id,
            client_id=client_id,
            scopes=scopes,
            resource=resource,
            ttl=refresh_ttl,
        )
        return access, refresh, int(access_ttl.total_seconds())


def _to_authorization_code(grant: OAuthAuthorizationGrantModel) -> AuthorizationCode:
    return AuthorizationCode(
        code=grant.code,
        scopes=list(grant.requested_scopes),
        expires_at=grant.expires_at.timestamp(),
        client_id=grant.client_id,
        code_challenge=grant.code_challenge,
        redirect_uri=AnyUrl(grant.redirect_uri),
        redirect_uri_provided_explicitly=grant.redirect_uri_explicit,
        resource=grant.resource,
    )
