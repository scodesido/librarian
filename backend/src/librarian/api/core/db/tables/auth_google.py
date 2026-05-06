from datetime import datetime

from librarian.api.core.db.table import Table, TableModel
from librarian.api.core.oauth.google.crypto import decrypt as decrypt_google_token


class AuthGoogleModel(TableModel):
    user_id: int
    sub: str
    email: str
    refresh_token_enc: bytes
    scopes: list[str]
    created_at: datetime
    updated_at: datetime

    @property
    def refresh_token(self) -> str:
        return decrypt_google_token(self.refresh_token_enc)


class AuthGoogle(Table):
    async def for_sub(self, sub: str) -> AuthGoogleModel | None:
        record = await self.conn.fetchrow(
            (
                "SELECT user_id, sub, email, refresh_token_enc, scopes, "
                "created_at, updated_at FROM auth_google WHERE sub = $1"
            ),
            sub,
        )
        return AuthGoogleModel.from_record(record)

    async def for_user(self, user_id: int) -> AuthGoogleModel | None:
        record = await self.conn.fetchrow(
            (
                "SELECT user_id, sub, email, refresh_token_enc, scopes, "
                "created_at, updated_at FROM auth_google WHERE user_id = $1"
            ),
            user_id,
        )
        return AuthGoogleModel.from_record(record)

    async def create(
        self,
        user_id: int,
        sub: str,
        email: str,
        refresh_token_enc: bytes,
        scopes: list[str],
    ) -> None:
        await self.conn.execute(
            (
                "INSERT INTO auth_google "
                "(user_id, sub, email, refresh_token_enc, scopes) "
                "VALUES ($1, $2, $3, $4, $5)"
            ),
            user_id,
            sub,
            email,
            refresh_token_enc,
            scopes,
        )

    async def update_tokens(
        self,
        user_id: int,
        email: str,
        refresh_token_enc: bytes,
        scopes: list[str],
    ) -> None:
        await self.conn.execute(
            (
                "UPDATE auth_google "
                "SET email = $2, refresh_token_enc = $3, scopes = $4 "
                "WHERE user_id = $1"
            ),
            user_id,
            email,
            refresh_token_enc,
            scopes,
        )
