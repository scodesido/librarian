from datetime import datetime

from librarian.db.table import Table, TableModel


class DataNodeEdgesModel(TableModel):
    node_edge_id: int
    user_id: int
    parent_node_id: int
    child_node_id: int
    created_at: datetime


class DataNodeEdges(Table):
    async def create(
        self, user_id: int, parent_node_id: int, child_node_id: int
    ) -> int:
        edge_id: int = await self.conn.fetchval(
            (
                "INSERT INTO data_node_edges (user_id, parent_node_id, child_node_id) "
                "VALUES ($1, $2, $3) RETURNING node_edge_id"
            ),
            user_id,
            parent_node_id,
            child_node_id,
        )
        return edge_id

    async def list_child_node_ids(self, user_id: int, parent_node_id: int) -> list[int]:
        rows = await self.conn.fetch(
            "SELECT child_node_id FROM data_node_edges "
            "WHERE user_id = $1 AND parent_node_id = $2",
            user_id,
            parent_node_id,
        )
        return [row["child_node_id"] for row in rows]

    async def list_parent_node_ids(self, user_id: int, child_node_id: int) -> list[int]:
        # Multi-parent is allowed by the schema (data_node_edges has no
        # UNIQUE on child_node_id) even though the current algorithm only
        # creates single-parent edges. Returning a list keeps the door
        # open; callers that assume single-parent assert on len(...) == 1.
        rows = await self.conn.fetch(
            "SELECT parent_node_id FROM data_node_edges "
            "WHERE user_id = $1 AND child_node_id = $2",
            user_id,
            child_node_id,
        )
        return [row["parent_node_id"] for row in rows]
