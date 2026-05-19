from dataclasses import dataclass

import numpy as np
from asyncpg.pool import PoolConnectionProxy
from numpy.typing import NDArray

from librarian.db.tables.data_blob_edges import DataBlobEdges
from librarian.db.tables.data_node_edges import DataNodeEdges
from librarian.db.tables.data_nodes import DataNodes
from librarian.service.tree_builder.distance import euclidean, weighted_distance


@dataclass
class Child:
    # Either a node child (is_blob=False, has blob_count) or a blob child
    # (is_blob=True, blob_count=1 by convention).
    is_blob: bool
    child_id: int
    representative: NDArray[np.float32]
    blob_count: int


async def find_overfull_node(
    conn: PoolConnectionProxy, user_id: int, k: int
) -> tuple[int, int, bool] | None:
    """Return (node_id, height, is_root) for some node with more than k
    children (counting node_edges + blob_edges where it is the parent), or
    None if the tree is settled.

    Splits propagate upward: an over-K node's split creates two new same-
    height siblings under its grandparent, and the grandparent may now be
    over-K. The query returns the highest-height candidate first so the
    propagation walks toward the root naturally rather than zigzagging.
    """
    record = await conn.fetchrow(
        """
        SELECT n.node_id, n.height, n.is_root
        FROM data_nodes n
        WHERE n.user_id = $1
          AND (
              (SELECT count(*) FROM data_node_edges
               WHERE parent_node_id = n.node_id)
              + (SELECT count(*) FROM data_blob_edges
                 WHERE parent_node_id = n.node_id)
          ) > $2
        ORDER BY n.height DESC
        LIMIT 1
        """,
        user_id,
        k,
    )
    if record is None:
        return None
    return record["node_id"], record["height"], record["is_root"]


async def list_children(
    conn: PoolConnectionProxy, user_id: int, parent_node_id: int, height: int
) -> list[Child]:
    """Children of `parent_node_id`. For height>0 the children are nodes
    (representative = centroid, blob_count from data_node_weights); for
    height=0 the children are blobs (representative = embedding_with_file,
    blob_count = 1).
    """
    if height == 0:
        rows = await conn.fetch(
            "SELECT e.child_blob_id, b.embedding_with_file "
            "FROM data_blob_edges e "
            "JOIN data_blobs b ON b.blob_id = e.child_blob_id "
            "WHERE e.user_id = $1 AND e.parent_node_id = $2",
            user_id,
            parent_node_id,
        )
        return [
            Child(
                is_blob=True,
                child_id=r["child_blob_id"],
                representative=np.asarray(r["embedding_with_file"], dtype=np.float32),
                blob_count=1,
            )
            for r in rows
        ]
    rows = await conn.fetch(
        "SELECT e.child_node_id, w.centroid, w.blob_count "
        "FROM data_node_edges e "
        "JOIN data_node_weights w ON w.node_id = e.child_node_id "
        "WHERE e.user_id = $1 AND e.parent_node_id = $2",
        user_id,
        parent_node_id,
    )
    return [
        Child(
            is_blob=False,
            child_id=r["child_node_id"],
            representative=np.asarray(r["centroid"], dtype=np.float32),
            blob_count=r["blob_count"],
        )
        for r in rows
    ]


def pick_furthest_pair(children: list[Child]) -> tuple[int, int]:
    """Indices i, j (i != j) of the two children whose representative
    vectors are furthest apart by euclidean distance. O(K^2) over children;
    K is small (max_children_per_node + 1 at worst).
    """
    best = (0.0, 0, 1)
    for i in range(len(children)):
        for j in range(i + 1, len(children)):
            d = euclidean(children[i].representative, children[j].representative)
            if d > best[0]:
                best = (d, i, j)
    return best[1], best[2]


def assign_children_to_seeds(
    children: list[Child],
    seed_a_idx: int,
    seed_b_idx: int,
    alpha: float,
) -> tuple[list[Child], list[Child]]:
    """Greedy assignment of children to one of two seeds.

    Order: descending blob_count (largest mass placed first, smaller blobs
    fill the gaps). For each child, distance is computed against each
    seed's *current centroid* (the running mean of the children already
    assigned to it) with the same imbalance penalty as the descent
    formula, so already-fuller seeds look proportionally farther.
    """
    seeds = [children[seed_a_idx], children[seed_b_idx]]
    groups: list[list[Child]] = [[seeds[0]], [seeds[1]]]
    sums: list[NDArray[np.float32]] = [
        seeds[0].representative.copy() * seeds[0].blob_count,
        seeds[1].representative.copy() * seeds[1].blob_count,
    ]
    counts: list[int] = [seeds[0].blob_count, seeds[1].blob_count]

    remaining_idx = [
        i for i in range(len(children)) if i != seed_a_idx and i != seed_b_idx
    ]
    remaining_idx.sort(key=lambda i: -children[i].blob_count)

    for i in remaining_idx:
        child = children[i]
        centroids = [(sums[s] / counts[s]).astype(np.float32) for s in (0, 1)]
        mean = (counts[0] + counts[1]) / 2.0
        dists = [
            weighted_distance(
                child.representative, centroids[s], counts[s], mean, alpha
            )
            for s in (0, 1)
        ]
        target = 0 if dists[0] <= dists[1] else 1
        groups[target].append(child)
        sums[target] = sums[target] + child.representative * child.blob_count
        counts[target] += child.blob_count

    return groups[0], groups[1]


async def split_one_overfull(
    conn: PoolConnectionProxy, user_id: int, k: int, alpha: float
) -> bool:
    """Split one over-K node. Returns True if a split happened, False if
    no over-K node exists.

    Algorithm (one transaction):
      1. Locate the over-K node N and its grandparent G (creating a new
         root above N if N itself is the root).
      2. List N's children (nodes or blobs depending on N.height).
      3. Pick the two seed children with the furthest representative
         vectors.
      4. Greedy-assign all children to one of the two seeds using the
         weighted-distance formula with a running-centroid update.
      5. Materialise two new nodes N1, N2 at N.height and edges
         G->N1, G->N2.
      6. Delete N. FK cascades remove its old outgoing edges to its
         former children and its incoming edge from the old grandparent;
         deferred orphan-collection runs at commit (no-ops because N is
         gone and G is now anchored by N1/N2).
      7. Create the new edges N1->{group1 children}, N2->{group2
         children}. Done after the delete so the unique constraint on
         data_blob_edges.child_blob_id is not transiently violated for
         leaf splits.
    """
    target = await find_overfull_node(conn, user_id, k)
    if target is None:
        return False
    node_id, height, is_root = target

    children = await list_children(conn, user_id, node_id, height)
    if len(children) <= k:
        # Race with concurrent rebalance; nothing to do.
        return False

    seed_a, seed_b = pick_furthest_pair(children)
    group_a, group_b = assign_children_to_seeds(children, seed_a, seed_b, alpha)

    nodes = DataNodes(conn)
    node_edges = DataNodeEdges(conn)
    blob_edges = DataBlobEdges(conn)

    # Grandparent: either the existing parent of N, or a new root one
    # level higher if N was the root.
    if is_root:
        grandparent_id = await nodes.create(user_id, height=height + 1, is_root=True)
    else:
        parents = await node_edges.list_parent_node_ids(user_id, node_id)
        if len(parents) != 1:
            raise RuntimeError(
                f"tree_builder split: node {node_id} has {len(parents)} parents; "
                "the current algorithm assumes single-parent edges"
            )
        grandparent_id = parents[0]

    new_a = await nodes.create(user_id, height=height, is_root=False)
    new_b = await nodes.create(user_id, height=height, is_root=False)

    await node_edges.create(user_id, grandparent_id, new_a)
    await node_edges.create(user_id, grandparent_id, new_b)

    # Drop N before reattaching its former children: data_blob_edges has
    # UNIQUE(child_blob_id), so a new N1->blob edge would collide with the
    # still-existing N->blob edge if we created it first.
    await nodes.delete(user_id, node_id)

    for new_parent, group in ((new_a, group_a), (new_b, group_b)):
        for child in group:
            if child.is_blob:
                await blob_edges.create(user_id, new_parent, child.child_id)
            else:
                await node_edges.create(user_id, new_parent, child.child_id)

    return True
