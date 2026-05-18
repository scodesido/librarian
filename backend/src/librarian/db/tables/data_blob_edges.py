from datetime import datetime

from librarian.db.table import Table, TableModel


class DataBlobEdgesModel(TableModel):
    blob_edge_id: int
    user_id: int
    parent_node_id: int
    child_blob_id: int
    created_at: datetime


class DataBlobEdges(Table):
    async def create(
        self, user_id: int, parent_node_id: int, child_blob_id: int
    ) -> int:
        edge_id: int = await self.conn.fetchval(
            (
                "INSERT INTO data_blob_edges (user_id, parent_node_id, child_blob_id) "
                "VALUES ($1, $2, $3) RETURNING blob_edge_id"
            ),
            user_id,
            parent_node_id,
            child_blob_id,
        )
        return edge_id

    async def list_child_blob_ids(self, user_id: int, parent_node_id: int) -> list[int]:
        rows = await self.conn.fetch(
            "SELECT child_blob_id FROM data_blob_edges "
            "WHERE user_id = $1 AND parent_node_id = $2",
            user_id,
            parent_node_id,
        )
        return [row["child_blob_id"] for row in rows]
