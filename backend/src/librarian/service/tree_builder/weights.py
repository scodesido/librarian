import numpy as np
from asyncpg.pool import PoolConnectionProxy
from numpy.typing import NDArray

from librarian.db.tables.data_node_weights import DataNodeWeights
from librarian.service.tree_builder.distance import normalize_l2


async def backfill_one_weight(conn: PoolConnectionProxy, user_id: int) -> bool:
    """Find a node missing its weight whose dependencies are already
    satisfied, compute the weight, and insert it. Returns True if a
    weight was inserted, False if no backfillable node exists.

    A height-0 node is always backfillable (its dependencies are blob
    embeddings, which exist as soon as the blob_edge does). A
    height>0 node is backfillable iff every one of its node-children
    has a weight already.

    The query orders by height ascending so that backfill proceeds
    bottom-up; in steady state this matches the order in which children
    invalidate parents.
    """
    record = await conn.fetchrow(
        """
        SELECT n.node_id, n.height
        FROM data_nodes n
        WHERE n.user_id = $1
          AND NOT EXISTS (
              SELECT 1 FROM data_node_weights w WHERE w.node_id = n.node_id
          )
          AND (
              n.height = 0
              OR NOT EXISTS (
                  SELECT 1 FROM data_node_edges e
                  WHERE e.parent_node_id = n.node_id
                    AND NOT EXISTS (
                        SELECT 1 FROM data_node_weights w2
                        WHERE w2.node_id = e.child_node_id
                    )
              )
          )
        ORDER BY n.height
        LIMIT 1
        """,
        user_id,
    )
    if record is None:
        return False
    node_id: int = record["node_id"]
    height: int = record["height"]

    if height == 0:
        centroid, blob_count = await compute_leaf_weight(conn, user_id, node_id)
    else:
        centroid, blob_count = await compute_internal_weight(conn, user_id, node_id)

    if blob_count == 0:
        # A node with no children survived the deferred orphan-collection
        # trigger somehow; treat this as a logic bug we want to see.
        raise RuntimeError(
            f"tree_builder: node {node_id} has zero children at backfill time"
        )

    await DataNodeWeights(conn).insert(user_id, node_id, centroid, blob_count)
    return True


async def compute_leaf_weight(
    conn: PoolConnectionProxy, user_id: int, node_id: int
) -> tuple[NDArray[np.float32], int]:
    """Centroid = L2-normalize(mean(embedding_with_file)) over child blobs;
    blob_count = number of child blobs.
    """
    rows = await conn.fetch(
        "SELECT b.embedding_with_file "
        "FROM data_blob_edges e "
        "JOIN data_blob_file_embeddings b ON b.blob_id = e.child_blob_id "
        "WHERE e.user_id = $1 AND e.parent_node_id = $2",
        user_id,
        node_id,
    )
    if not rows:
        return np.zeros((1,), dtype=np.float32), 0
    vectors = np.stack(
        [np.asarray(r["embedding_with_file"], dtype=np.float32) for r in rows]
    )
    centroid = normalize_l2(vectors.mean(axis=0).astype(np.float32))
    return centroid, len(rows)


async def compute_internal_weight(
    conn: PoolConnectionProxy, user_id: int, node_id: int
) -> tuple[NDArray[np.float32], int]:
    """Centroid = L2-normalize(weighted mean of child centroids, weights =
    child blob_counts); blob_count = sum of child blob_counts.
    """
    rows = await conn.fetch(
        "SELECT w.centroid, w.blob_count "
        "FROM data_node_edges e "
        "JOIN data_node_weights w ON w.node_id = e.child_node_id "
        "WHERE e.user_id = $1 AND e.parent_node_id = $2",
        user_id,
        node_id,
    )
    if not rows:
        return np.zeros((1,), dtype=np.float32), 0
    centroids = np.stack([np.asarray(r["centroid"], dtype=np.float32) for r in rows])
    counts = np.array([r["blob_count"] for r in rows], dtype=np.float32)
    total = int(counts.sum())
    weighted = (centroids * counts[:, None]).sum(axis=0) / counts.sum()
    centroid = normalize_l2(weighted.astype(np.float32))
    return centroid, total
