from dataclasses import dataclass
from typing import Any

import numpy as np
from asyncpg.pool import PoolConnectionProxy
from numpy.typing import NDArray

from librarian.db.tables.data_blobs import DataBlobs


@dataclass
class PreparedBlob:
    file_blob_index: int
    file_start: int
    file_end: int
    embedding_blob: NDArray[np.float32]
    embedding_with_file: NDArray[np.float32]
    abstract: dict[str, Any]


async def insert_blobs_end_to_beginning(
    conn: PoolConnectionProxy,
    user_id: int,
    file_id: int,
    prepared: list[PreparedBlob],
) -> None:
    """Insert blobs in reverse order so that next_blob_id always points at
    an already-inserted row. The last prepared blob becomes the tail
    (is_final_blob=TRUE, next_blob_id=NULL); each preceding blob points
    forward to the one inserted just before it.

    Must be called inside an open transaction. The caller is responsible
    for that boundary.
    """
    if not prepared:
        return
    blobs = DataBlobs(conn)
    next_blob_id: int | None = None
    for prep in reversed(prepared):
        is_final = next_blob_id is None
        inserted_id = await blobs.insert_one(
            user_id=user_id,
            file_id=file_id,
            file_blob_index=prep.file_blob_index,
            file_start=prep.file_start,
            file_end=prep.file_end,
            is_final_blob=is_final,
            next_blob_id=next_blob_id,
            embedding_blob=prep.embedding_blob,
            embedding_with_file=prep.embedding_with_file,
            abstract=prep.abstract,
        )
        next_blob_id = inserted_id
