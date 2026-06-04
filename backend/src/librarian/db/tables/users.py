from datetime import datetime

from librarian.db.table import Table, TableModel


class UsersModel(TableModel):
    id: int
    user_name: str
    created_at: datetime
    updated_at: datetime


class Users(Table):
    async def by_id(self, user_id: int) -> UsersModel | None:
        record = await self.conn.fetchrow(
            "SELECT id, user_name, created_at, updated_at FROM users WHERE id = $1",
            user_id,
        )
        return UsersModel.from_record(record)

    async def list_all(self) -> list[UsersModel]:
        records = await self.conn.fetch(
            "SELECT id, user_name, created_at, updated_at FROM users ORDER BY id"
        )
        return [UsersModel.model_validate(dict(r)) for r in records]

    async def create(self, user_name: str) -> int:
        user_id: int = await self.conn.fetchval(
            "INSERT INTO users (user_name) VALUES ($1) RETURNING id",
            user_name,
        )
        return user_id
