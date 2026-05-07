import secrets
from datetime import datetime, timedelta, timezone

from librarian.db.table import Table, TableModel


class AuthSessionsModel(TableModel):
    id: str
    user_id: int
    created_at: datetime
    expires_at: datetime


class AuthSessions(Table):
    async def create(self, user_id: int, ttl: timedelta) -> str:
        session_id = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + ttl
        await self.conn.execute(
            "INSERT INTO auth_sessions (id, user_id, expires_at) VALUES ($1, $2, $3)",
            session_id,
            user_id,
            expires_at,
        )
        return session_id

    async def resolve(self, session_id: str) -> int | None:
        user_id: int | None = await self.conn.fetchval(
            "SELECT user_id FROM auth_sessions WHERE id = $1 AND expires_at > now()",
            session_id,
        )
        return user_id

    async def delete(self, session_id: str) -> None:
        await self.conn.execute(
            "DELETE FROM auth_sessions WHERE id = $1",
            session_id,
        )
