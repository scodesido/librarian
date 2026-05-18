from dataclasses import dataclass

import numpy as np
from asyncpg.pool import PoolConnectionProxy
from numpy.typing import NDArray

from librarian.db.tables.data_nodes import DataNodes
from librarian.service.tree_builder.distance import weighted_distance


class MissingCentroidError(Exception):
    """A descent step needed a child's centroid but none exists yet.

    Raised so the enclosing transaction aborts. The next worker iteration
    will backfill the missing weight before retrying the insertion.
    """


@dataclass
class NodeChild:
    node_id: int
    centroid: NDArray[np.float32]
    blob_count: int


async def list_node_children_with_weights(
    conn: PoolConnectionProxy, user_id: int, parent_node_id: int
) -> list[NodeChild]:
    """Children of `parent_node_id` paired with their centroids and
    blob_counts. Raises MissingCentroidError if any child lacks a weight,
    so the caller's transaction aborts.
    """
    rows = await conn.fetch(
        "SELECT e.child_node_id, w.centroid, w.blob_count "
        "FROM data_node_edges e "
        "LEFT JOIN data_node_weights w ON w.node_id = e.child_node_id "
        "WHERE e.user_id = $1 AND e.parent_node_id = $2",
        user_id,
        parent_node_id,
    )
    children: list[NodeChild] = []
    for row in rows:
        if row["centroid"] is None:
            raise MissingCentroidError(
                f"node {row['child_node_id']} (child of {parent_node_id}) "
                "has no weight; backfill must run first"
            )
        children.append(
            NodeChild(
                node_id=row["child_node_id"],
                centroid=np.asarray(row["centroid"], dtype=np.float32),
                blob_count=row["blob_count"],
            )
        )
    return children


async def descend_for_blob(
    conn: PoolConnectionProxy,
    user_id: int,
    root_node_id: int,
    embedding_with_file: NDArray[np.float32],
    alpha: float,
) -> int:
    """Descend from the root to a height-0 leaf node and return its id.

    At each internal level we pick the child whose weighted distance to
    `embedding_with_file` is smallest. Pure euclidean distance, biased by
    `(child_blob_count / mean_blob_count)^alpha` so that less-populated
    subtrees attract more.
    """
    nodes = DataNodes(conn)
    current_id = root_node_id
    while True:
        current = await nodes.get(user_id, current_id)
        if current is None:
            raise RuntimeError(
                f"tree_builder descent: node {current_id} disappeared mid-traversal"
            )
        if current.height == 0:
            return current_id
        children = await list_node_children_with_weights(conn, user_id, current_id)
        if not children:
            raise RuntimeError(
                f"tree_builder descent: internal node {current_id} has no children"
            )
        mean_count = float(np.mean([c.blob_count for c in children]))
        best = min(
            children,
            key=lambda c: weighted_distance(
                embedding_with_file, c.centroid, c.blob_count, mean_count, alpha
            ),
        )
        current_id = best.node_id
