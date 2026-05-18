from asyncpg.pool import PoolConnectionProxy


async def pick_user_with_work(conn: PoolConnectionProxy) -> int | None:
    """Return the user_id of some user with tree_builder work pending, or
    None if everyone is settled.

    Work means at least one of:
      * a data_nodes row without a matching data_node_weights row (weight
        backfill pending);
      * a data_nodes row with more than max_children_per_node children
        (split pending) -- not checked here because K is a Python-level
        setting; the worker's run_iteration consults this directly;
      * a data_blobs row whose file is ready (has is_final_blob=TRUE) and
        which lacks a data_blob_edges row (insertion pending).

    We don't try to be fair across users; any user with any signal is
    acceptable. The advisory lock the worker takes after this query
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
        LIMIT 1
        """
    )
    if record is None:
        return None
    user_id: int = record["user_id"]
    return user_id
