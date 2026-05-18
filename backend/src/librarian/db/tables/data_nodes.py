from datetime import datetime

from librarian.db.table import Table, TableModel


class DataNodesModel(TableModel):
    node_id: int
    user_id: int
    is_root: bool
    height: int
    created_at: datetime


SELECT_COLUMNS = "node_id, user_id, is_root, height, created_at"


class DataNodes(Table):
    async def create(self, user_id: int, height: int, is_root: bool) -> int:
        node_id: int = await self.conn.fetchval(
            (
                "INSERT INTO data_nodes (user_id, is_root, height) "
                "VALUES ($1, $2, $3) RETURNING node_id"
            ),
            user_id,
            is_root,
            height,
        )
        return node_id

    async def get(self, user_id: int, node_id: int) -> DataNodesModel | None:
        record = await self.conn.fetchrow(
            f"SELECT {SELECT_COLUMNS} FROM data_nodes "
            "WHERE user_id = $1 AND node_id = $2",
            user_id,
            node_id,
        )
        return DataNodesModel.from_record(record)

    async def find_root(self, user_id: int) -> DataNodesModel | None:
        record = await self.conn.fetchrow(
            f"SELECT {SELECT_COLUMNS} FROM data_nodes WHERE user_id = $1 AND is_root",
            user_id,
        )
        return DataNodesModel.from_record(record)

    async def delete(self, user_id: int, node_id: int) -> None:
        await self.conn.execute(
            "DELETE FROM data_nodes WHERE user_id = $1 AND node_id = $2",
            user_id,
            node_id,
        )
