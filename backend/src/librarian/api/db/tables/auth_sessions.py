from datetime import datetime

from librarian.api.db.table import Table, TableModel


class AuthSessionsModel(TableModel):
    id: str
    user_name: str
    created_at: datetime
    expires_at: datetime


class AuthSessions(Table):
    async def for_user(self, user_name: str) -> AuthSessionsModel | None:
        record = await self.conn.fetchrow(
            "SELECT id, user_name, created_at, expires_at FROM auth_sessions WHERE user_name = $1",
            user_name,
        )
        return AuthSessionsModel.from_record(record)
