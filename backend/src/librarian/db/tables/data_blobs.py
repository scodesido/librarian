from datetime import datetime
from typing import Any

import numpy as np
from numpy.typing import NDArray

from librarian.db.table import Table, TableModel


class DataBlobsModel(TableModel):
    blob_id: int
    user_id: int
    file_id: int
    file_blob_index: int
    file_start: int
    file_end: int
    is_final_blob: bool
    next_blob_id: int | None
    abstract: dict[str, Any]
    created_at: datetime


class DataBlobs(Table):
    async def insert_one(
        self,
        user_id: int,
        file_id: int,
        file_blob_index: int,
        file_start: int,
        file_end: int,
        is_final_blob: bool,
        next_blob_id: int | None,
        embedding_blob: NDArray[np.float32],
        embedding_with_file: NDArray[np.float32],
        abstract: dict[str, Any],
    ) -> int:
        blob_id: int = await self.conn.fetchval(
            (
                "INSERT INTO data_blobs ("
                "  user_id, file_id, file_blob_index, file_start, file_end,"
                "  is_final_blob, next_blob_id,"
                "  embedding_blob, embedding_with_file, abstract"
                ") VALUES ("
                "  $1, $2, $3, $4, $5, $6, $7, $8, $9, $10"
                ") RETURNING blob_id"
            ),
            user_id,
            file_id,
            file_blob_index,
            file_start,
            file_end,
            is_final_blob,
            next_blob_id,
            embedding_blob,
            embedding_with_file,
            abstract,
        )
        return blob_id
