import numpy as np
from asyncpg.pool import PoolConnectionProxy

from librarian.db.tables.data_blob_edges import DataBlobEdges
from librarian.db.tables.data_nodes import DataNodes
from librarian.service.tree_builder.descend import descend_for_blob


async def find_ready_file_with_unattached_blobs(
    conn: PoolConnectionProxy, user_id: int
) -> int | None:
    """Return a file_id whose final blob exists (the file is "ready") and
    which has at least one blob without a data_blob_edges row. None if
    every ready file is fully inserted.
    """
    record = await conn.fetchrow(
        """
        SELECT DISTINCT b.file_id
        FROM data_blobs b
        WHERE b.user_id = $1
          AND NOT EXISTS (
              SELECT 1 FROM data_blob_edges e WHERE e.child_blob_id = b.blob_id
          )
          AND EXISTS (
              SELECT 1 FROM data_blobs bf
              WHERE bf.file_id = b.file_id AND bf.is_final_blob
          )
        LIMIT 1
        """,
        user_id,
    )
    if record is None:
        return None
    file_id: int = record["file_id"]
    return file_id


async def insert_one_ready_file(
    conn: PoolConnectionProxy, user_id: int, alpha: float
) -> bool:
    """Insert every blob of one ready, not-yet-attached file into the tree.
    Returns True if a file was processed, False if no candidate file exists.

    All of the file's blob_edges land in a single transaction (the caller's).
    The descent for each blob runs over the tree's current state, so blobs
    of the same file may end up under different leaf nodes if the tree's
    descent diverges (the per-blob descent is independent).
    """
    file_id = await find_ready_file_with_unattached_blobs(conn, user_id)
    if file_id is None:
        return False

    rows = await conn.fetch(
        "SELECT b.blob_id, b.embedding_with_file "
        "FROM data_blobs b "
        "WHERE b.user_id = $1 AND b.file_id = $2 "
        "  AND NOT EXISTS ("
        "      SELECT 1 FROM data_blob_edges e WHERE e.child_blob_id = b.blob_id"
        "  ) "
        "ORDER BY b.file_blob_index",
        user_id,
        file_id,
    )

    nodes = DataNodes(conn)
    edges = DataBlobEdges(conn)
    root = await nodes.find_root(user_id)
    if root is None:
        root_node_id = await nodes.create(user_id, height=0, is_root=True)
    else:
        root_node_id = root.node_id

    for row in rows:
        blob_id: int = row["blob_id"]
        embedding = np.asarray(row["embedding_with_file"], dtype=np.float32)
        leaf_id = await descend_for_blob(conn, user_id, root_node_id, embedding, alpha)
        await edges.create(user_id, leaf_id, blob_id)
    return True
