from asyncpg.pool import PoolConnectionProxy

from librarian.db.tables.data_files import SELECT_COLUMNS, DataFilesModel


async def pick_user_with_unready_file(conn: PoolConnectionProxy) -> int | None:
    """Return the user_id of a random user with at least one PDF/TEXT
    file that hasn't been chunked into blobs yet. Random picking
    spreads work across users so a single user with broken credentials
    (or many pending files) doesn't starve the queue — the next
    iteration's random pick is just as likely to land on someone else.

    `random()` re-shuffles the candidate set on every call; under heavy
    contention this is fine because the result is one user, not a
    ranked list. None when no user has unready work.
    """
    record = await conn.fetchrow(
        """
        SELECT u.id AS user_id FROM users u
        WHERE EXISTS (
            SELECT 1 FROM data_files f
            WHERE f.user_id = u.id
              AND f.type IN ('PDF', 'TEXT')
              AND NOT EXISTS (
                  SELECT 1 FROM data_blobs b
                  WHERE b.file_id = f.file_id AND b.is_final_blob
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


async def claim_next_unready_file_for_user(
    conn: PoolConnectionProxy, user_id: int
) -> DataFilesModel | None:
    """Claim the oldest unready file for `user_id`. FOR UPDATE SKIP
    LOCKED so parallel workers landing on the same user race naturally
    on different files; the upstream random user pick is what spreads
    contention across users.

    None when the user's queue was drained between the upstream pick
    and this call (a parallel worker grabbed the last claimable file).
    The caller treats this as "no work done" and sleeps for the
    poll interval before trying again.
    """
    record = await conn.fetchrow(
        (
            f"SELECT {SELECT_COLUMNS} FROM data_files f "
            "WHERE f.user_id = $1 "
            "  AND f.type IN ('PDF', 'TEXT') "
            "  AND NOT EXISTS ("
            "    SELECT 1 FROM data_blobs b "
            "    WHERE b.file_id = f.file_id AND b.is_final_blob"
            "  ) "
            "ORDER BY f.created_at "
            "LIMIT 1 "
            "FOR UPDATE SKIP LOCKED"
        ),
        user_id,
    )
    return DataFilesModel.from_record(record)
