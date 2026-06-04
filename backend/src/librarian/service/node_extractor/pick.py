from asyncpg.pool import PoolConnectionProxy


async def pick_user_with_extractable_tree(
    conn: PoolConnectionProxy,
) -> int | None:
    """Return the user_id of a random user whose tree is "ready for
    extraction" and who has at least one node without an abstract. None
    otherwise.

    "Ready for extraction" is a per-user gate at iteration start (per the
    spec in docs/04.immutable_data_pipeline.md):
      * every PDF/TEXT file is fully processed (has file embeddings);
      * every blob has a data_blob_edges row (in the tree);
      * every node has a data_node_weights row (weighted).

    A soft gate: the tree could change mid-iteration (e.g. blob_extractor
    picks up a new file). In that case our INSERT lands but is invalidated
    shortly after by the edge-trigger cascade. The next iteration
    recomputes. We accept one wasted LLM call per disturbance in exchange
    for not serialising against tree_builder via a per-user advisory lock.

    Random user picking spreads work across users so a single user with
    broken credentials doesn't starve the queue — see blob_extractor/pick.py.
    """
    record = await conn.fetchrow(
        """
        SELECT u.id AS user_id FROM users u
        WHERE NOT EXISTS (
            SELECT 1 FROM data_files f
            WHERE f.user_id = u.id AND f.type IN ('PDF', 'TEXT')
              AND NOT EXISTS (
                  SELECT 1 FROM data_blob_file_embeddings e
                  WHERE e.file_id = f.file_id
              )
        )
        AND NOT EXISTS (
            SELECT 1 FROM data_blobs b
            WHERE b.user_id = u.id
              AND NOT EXISTS (
                  SELECT 1 FROM data_blob_edges e
                  WHERE e.child_blob_id = b.blob_id
              )
        )
        AND NOT EXISTS (
            SELECT 1 FROM data_nodes n
            WHERE n.user_id = u.id
              AND NOT EXISTS (
                  SELECT 1 FROM data_node_weights w
                  WHERE w.node_id = n.node_id
              )
        )
        AND EXISTS (
            SELECT 1 FROM data_nodes n
            WHERE n.user_id = u.id
              AND NOT EXISTS (
                  SELECT 1 FROM data_node_abstracts a
                  WHERE a.node_id = n.node_id
              )
        )
        ORDER BY random()
        LIMIT 1
        """
    )
    if record is None:
        return None
    user_id: int = record["user_id"]
    return user_id
