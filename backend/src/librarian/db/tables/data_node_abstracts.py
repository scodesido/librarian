from datetime import datetime
from typing import Any

from librarian.db.table import Table, TableModel


class DataNodeAbstractsModel(TableModel):
    node_abstract_id: int
    user_id: int
    node_id: int
    abstract: dict[str, Any]
    created_at: datetime


class DataNodeAbstracts(Table):
    async def insert(self, user_id: int, node_id: int, abstract: dict[str, Any]) -> int:
        node_abstract_id: int = await self.conn.fetchval(
            (
                "INSERT INTO data_node_abstracts (user_id, node_id, abstract) "
                "VALUES ($1, $2, $3) RETURNING node_abstract_id"
            ),
            user_id,
            node_id,
            abstract,
        )
        return node_abstract_id
