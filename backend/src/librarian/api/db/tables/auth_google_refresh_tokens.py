from datetime import datetime

from librarian.api.db.table import Table, TableModel


class AuthGoogleRefreshTokensModel(TableModel):
    user_name: str
    refresh_token_enc: bytes
    scopes: list[str]
    created_at: datetime
    updated_at: datetime


class AuthGoogleRefreshTokens(Table):
    async def for_user(self, user_name: str) -> AuthGoogleRefreshTokensModel | None:
        record = await self.conn.fetchrow(
            (
                "SELECT user_name, refresh_token_enc, scopes, created_at, updated_at "
                "FROM auth_google_refresh_tokens "
                "WHERE user_name = $1"
            ),
            user_name,
        )
        return AuthGoogleRefreshTokensModel.from_record(record)
