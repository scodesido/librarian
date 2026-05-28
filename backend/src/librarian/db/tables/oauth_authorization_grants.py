from datetime import datetime, timedelta, timezone
from typing import Literal

from librarian.db.table import Table, TableModel

GrantStatus = Literal["pending", "granted", "consumed"]


class OAuthAuthorizationGrantModel(TableModel):
    """Row shape for `oauth_authorization_grants`. Tracks one authorization
    code through its three states (pending consent, granted, consumed).
    """

    code: str
    client_id: str
    user_id: int | None
    redirect_uri: str
    redirect_uri_explicit: bool
    code_challenge: str
    requested_scopes: list[str]
    resource: str | None
    client_state: str | None
    status: GrantStatus
    expires_at: datetime
    created_at: datetime
    updated_at: datetime


class OAuthAuthorizationGrants(Table):
    async def create_pending(
        self,
        code: str,
        client_id: str,
        redirect_uri: str,
        redirect_uri_explicit: bool,
        code_challenge: str,
        requested_scopes: list[str],
        resource: str | None,
        client_state: str | None,
        ttl: timedelta,
    ) -> None:
        expires_at = datetime.now(timezone.utc) + ttl
        await self.conn.execute(
            (
                "INSERT INTO oauth_authorization_grants "
                "(code, client_id, redirect_uri, redirect_uri_explicit, "
                "code_challenge, requested_scopes, resource, client_state, "
                "status, expires_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'pending', $9)"
            ),
            code,
            client_id,
            redirect_uri,
            redirect_uri_explicit,
            code_challenge,
            requested_scopes,
            resource,
            client_state,
            expires_at,
        )

    async def get_pending(self, code: str) -> OAuthAuthorizationGrantModel | None:
        # `pending` is the only state where consent has not yet been
        # collected. The consent endpoints filter on it to refuse re-using
        # a code already granted or consumed.
        record = await self.conn.fetchrow(
            (
                "SELECT code, client_id, user_id, redirect_uri, "
                "redirect_uri_explicit, code_challenge, requested_scopes, "
                "resource, client_state, status, expires_at, created_at, "
                "updated_at FROM oauth_authorization_grants "
                "WHERE code = $1 AND status = 'pending' AND expires_at > now()"
            ),
            code,
        )
        return OAuthAuthorizationGrantModel.from_record(record)

    async def grant(self, code: str, user_id: int) -> bool:
        """Attach a user to a pending grant. Returns True if a row was
        moved from `pending` to `granted` (i.e. consent was applied to a
        still-valid grant), False otherwise (expired, wrong status, or
        gone).
        """
        result = await self.conn.execute(
            (
                "UPDATE oauth_authorization_grants "
                "SET user_id = $2, status = 'granted' "
                "WHERE code = $1 AND status = 'pending' AND expires_at > now()"
            ),
            code,
            user_id,
        )
        return result.endswith(" 1")

    async def load_granted(
        self, code: str, client_id: str
    ) -> OAuthAuthorizationGrantModel | None:
        # `load_authorization_code` on the provider: must match both the
        # code itself and the calling client. Status must be `granted`
        # (not yet redeemed) and not expired.
        record = await self.conn.fetchrow(
            (
                "SELECT code, client_id, user_id, redirect_uri, "
                "redirect_uri_explicit, code_challenge, requested_scopes, "
                "resource, client_state, status, expires_at, created_at, "
                "updated_at FROM oauth_authorization_grants "
                "WHERE code = $1 AND client_id = $2 "
                "AND status = 'granted' AND expires_at > now()"
            ),
            code,
            client_id,
        )
        return OAuthAuthorizationGrantModel.from_record(record)

    async def consume(self, code: str) -> bool:
        """Mark a granted code as consumed (the /token exchange ran). One-
        shot: any subsequent exchange of the same code must fail.
        """
        result = await self.conn.execute(
            (
                "UPDATE oauth_authorization_grants "
                "SET status = 'consumed' "
                "WHERE code = $1 AND status = 'granted'"
            ),
            code,
        )
        return result.endswith(" 1")
