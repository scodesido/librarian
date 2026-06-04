from asyncpg.pool import PoolConnectionProxy

from librarian.db.tables.data_files import SELECT_COLUMNS, DataFilesModel


async def pick_user_with_unready_file(conn: PoolConnectionProxy) -> int | None:
    """Return the user_id of a random user with at least one PDF/TEXT file
    that isn't fully processed yet. "Fully processed" is the existence of a
    data_blob_file_embeddings row for the file (written only as a complete
    set), so "unready" covers everything from "no manifest" through "blobs
    done but file embeddings missing".

    Random picking spreads work across users so a single user with broken
    credentials (or many pending files) doesn't starve the queue. None when
    no user has unready work.
    """
    record = await conn.fetchrow(
        """
        SELECT u.id AS user_id FROM users u
        WHERE EXISTS (
            SELECT 1 FROM data_files f
            WHERE f.user_id = u.id
              AND f.type IN ('PDF', 'TEXT')
              AND NOT EXISTS (
                  SELECT 1 FROM data_blob_file_embeddings e
                  WHERE e.file_id = f.file_id
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


async def claim_unready_file(
    conn: PoolConnectionProxy, user_id: int
) -> DataFilesModel | None:
    """Claim the oldest unready PDF/TEXT file for `user_id` by taking a
    session-level advisory lock on (user_id, file_id). Unlike a row
    `FOR UPDATE`, the advisory lock survives across the many short
    transactions the incremental extraction runs — it is what keeps a
    second worker off the same file (and from burning duplicate LLM
    calls). The caller MUST release it (`pg_advisory_unlock`) when done.

    Iterates oldest-first, skipping files another worker already holds, and
    re-checks readiness after locking (a parallel worker may have finished
    the file between the scan and the lock). None when the user's queue is
    drained or every unready file is locked by someone else.
    """
    rows = await conn.fetch(
        (
            f"SELECT {SELECT_COLUMNS} FROM data_files f "
            "WHERE f.user_id = $1 "
            "  AND f.type IN ('PDF', 'TEXT') "
            "  AND NOT EXISTS ("
            "    SELECT 1 FROM data_blob_file_embeddings e "
            "    WHERE e.file_id = f.file_id"
            "  ) "
            "ORDER BY f.created_at"
        ),
        user_id,
    )
    for record in rows:
        file = DataFilesModel.from_record(record)
        assert file is not None
        got = await conn.fetchval(
            "SELECT pg_try_advisory_lock($1, $2)", user_id, file.file_id
        )
        if not got:
            continue
        still_unready = await conn.fetchval(
            "SELECT NOT EXISTS("
            "  SELECT 1 FROM data_blob_file_embeddings WHERE file_id = $1"
            ")",
            file.file_id,
        )
        if still_unready:
            return file
        await conn.execute("SELECT pg_advisory_unlock($1, $2)", user_id, file.file_id)
    return None
