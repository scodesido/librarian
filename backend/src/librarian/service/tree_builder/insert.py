import numpy as np
from asyncpg.pool import PoolConnectionProxy
from numpy.typing import NDArray

from librarian.db.tables.data_blob_edges import DataBlobEdges
from librarian.db.tables.data_nodes import DataNodes
from librarian.service.tree_builder.descend import descend_for_blob


async def find_one_ready_unattached_blob(
    conn: PoolConnectionProxy, user_id: int
) -> tuple[int, NDArray[np.float32]] | None:
    """Return (blob_id, embedding_with_file) for the next blob to attach,
    or None if every ready file is fully inserted.

    A blob is eligible iff its file has its final blob present (i.e. the
    file is "ready") AND the blob itself has no data_blob_edges row yet.
    Ordering by (file_id, file_blob_index) means we finish all blobs of
    one file before moving on to the next, and `file_id` being BIGSERIAL
    makes that ordering stable across worker iterations: a newer file
    can never pre-empt an in-progress one.
    """
    record = await conn.fetchrow(
        """
        SELECT b.blob_id, b.embedding_with_file
        FROM data_blobs b
        WHERE b.user_id = $1
          AND NOT EXISTS (
              SELECT 1 FROM data_blob_edges e WHERE e.child_blob_id = b.blob_id
          )
          AND EXISTS (
              SELECT 1 FROM data_blobs bf
              WHERE bf.file_id = b.file_id AND bf.is_final_blob
          )
        ORDER BY b.file_id, b.file_blob_index
        LIMIT 1
        """,
        user_id,
    )
    if record is None:
        return None
    blob_id: int = record["blob_id"]
    embedding = np.asarray(record["embedding_with_file"], dtype=np.float32)
    return blob_id, embedding


async def insert_one_ready_blob(
    conn: PoolConnectionProxy, user_id: int, alpha: float
) -> bool:
    """Attach one blob of one ready, not-yet-attached file to the tree.
    Returns True if a blob was attached, False if no candidate exists.

    One blob per iteration (not the whole file): inserting a blob_edge
    invalidates the parent leaf's weight, and the data_node_weights
    invalidation trigger cascades the deletion up to the root within the
    same transaction. So a second descent in the same transaction would
    see a partially-invalidated tree and raise MissingCentroidError. By
    returning after one blob we let the worker's "weights first" priority
    refill the chain before the next descent.

    Atomicity across the file isn't needed: pick_user_with_work and the
    query above happily resume a half-attached file (it still has
    unattached blobs in a ready file). If the worker crashes mid-file,
    the next iteration picks up where it left off.
    """
    candidate = await find_one_ready_unattached_blob(conn, user_id)
    if candidate is None:
        return False
    blob_id, embedding = candidate

    nodes = DataNodes(conn)
    root = await nodes.find_root(user_id)
    if root is None:
        root_node_id = await nodes.create(user_id, height=0, is_root=True)
    else:
        root_node_id = root.node_id

    leaf_id = await descend_for_blob(conn, user_id, root_node_id, embedding, alpha)
    await DataBlobEdges(conn).create(user_id, leaf_id, blob_id)
    return True
