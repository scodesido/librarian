from asyncpg.pool import PoolConnectionProxy


async def pick_user_with_work(conn: PoolConnectionProxy, k: int) -> int | None:
    """Return the user_id of a random user with tree_builder work pending,
    or None if everyone is settled.

    Work means at least one of:
      * a data_nodes row without a matching data_node_weights row (weight
        backfill pending);
      * a data_nodes row with more than `k` children counting
        data_node_edges + data_blob_edges where it is the parent (split
        pending);
      * a data_blobs row whose file is ready (has is_final_blob=TRUE) and
        which lacks a data_blob_edges row (insertion pending).

    Random user picking spreads work across users so the union-all
    candidate set doesn't lean toward whichever user happens to have the
    earliest row. The advisory lock the worker takes after this query
    serialises per-user concurrent work.
    """
    record = await conn.fetchrow(
        """
        SELECT user_id FROM (
            SELECT n.user_id
            FROM data_nodes n
            WHERE NOT EXISTS (
                SELECT 1 FROM data_node_weights w WHERE w.node_id = n.node_id
            )
            UNION ALL
            SELECT n.user_id
            FROM data_nodes n
            WHERE (
                (SELECT count(*) FROM data_node_edges
                 WHERE parent_node_id = n.node_id)
                + (SELECT count(*) FROM data_blob_edges
                   WHERE parent_node_id = n.node_id)
            ) > $1
            UNION ALL
            SELECT b.user_id
            FROM data_blobs b
            WHERE NOT EXISTS (
                SELECT 1 FROM data_blob_edges e WHERE e.child_blob_id = b.blob_id
            )
            AND EXISTS (
                SELECT 1 FROM data_blobs bf
                WHERE bf.file_id = b.file_id AND bf.is_final_blob
            )
        ) AS work
        ORDER BY random()
        LIMIT 1
        """,
        k,
    )
    if record is None:
        return None
    user_id: int = record["user_id"]
    return user_id
