from datetime import datetime
from typing import Any, Literal

from librarian.db.table import Table, TableModel

NodeState = Literal["PENDING", "PROCESSING", "READY", "FAILED"]


class TreeNodesModel(TableModel):
    node_id: int
    user_id: int
    blob_id: int | None
    abstract: dict[str, Any] | None
    height: int
    state: NodeState
    created_at: datetime
    updated_at: datetime


class TreeNodes(Table):
    async def create_leaf(
        self,
        user_id: int,
        blob_id: int,
        abstract: dict[str, Any],
    ) -> int:
        node_id: int = await self.conn.fetchval(
            (
                "INSERT INTO tree_nodes "
                "(user_id, blob_id, abstract, height, state) "
                "VALUES ($1, $2, $3, 0, 'READY') "
                "RETURNING node_id"
            ),
            user_id,
            blob_id,
            abstract,
        )
        return node_id
