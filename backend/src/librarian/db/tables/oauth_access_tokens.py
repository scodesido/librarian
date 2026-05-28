from datetime import datetime, timedelta, timezone

from librarian.db.table import Table, TableModel


class OAuthAccessTokenModel(TableModel):
    token_hash: bytes
    user_id: int
    client_id: str
    scopes: list[str]
    resource: str | None
    expires_at: datetime
    created_at: datetime


class OAuthAccessTokens(Table):
    async def create(
        self,
        token_hash: bytes,
        user_id: int,
        client_id: str,
        scopes: list[str],
        resource: str | None,
        ttl: timedelta,
    ) -> None:
        expires_at = datetime.now(timezone.utc) + ttl
        await self.conn.execute(
            (
                "INSERT INTO oauth_access_tokens "
                "(token_hash, user_id, client_id, scopes, resource, expires_at) "
                "VALUES ($1, $2, $3, $4, $5, $6)"
            ),
            token_hash,
            user_id,
            client_id,
            scopes,
            resource,
            expires_at,
        )

    async def load(self, token_hash: bytes) -> OAuthAccessTokenModel | None:
        # Expired rows are filtered server-side. A background sweep is a
        # later optimisation — for now expired tokens stay in the table
        # but are invisible to the bearer middleware.
        record = await self.conn.fetchrow(
            (
                "SELECT token_hash, user_id, client_id, scopes, resource, "
                "expires_at, created_at FROM oauth_access_tokens "
                "WHERE token_hash = $1 AND expires_at > now()"
            ),
            token_hash,
        )
        return OAuthAccessTokenModel.from_record(record)

    async def revoke(self, token_hash: bytes) -> None:
        await self.conn.execute(
            "DELETE FROM oauth_access_tokens WHERE token_hash = $1",
            token_hash,
        )
