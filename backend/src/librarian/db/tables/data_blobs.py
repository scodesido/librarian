from datetime import datetime
from typing import Any

import numpy as np
from numpy.typing import NDArray

from librarian.db.table import Table, TableModel

# embedding_blob and embedding_with_file are deliberately excluded: the
# former is large and only needed by the file-embedding computation
# (fetch_embedding_blobs), the latter now lives in data_blob_file_embeddings.
SELECT_COLUMNS = (
    "blob_id, user_id, file_id, file_blob_index, file_start, file_end, "
    "abstract, created_at"
)


class DataBlobsModel(TableModel):
    blob_id: int
    user_id: int
    file_id: int
    file_blob_index: int
    file_start: int
    file_end: int
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
        embedding_blob: NDArray[np.float32],
        abstract: dict[str, Any],
    ) -> int:
        """Insert one blob and return its blob_id. Built incrementally,
        forward (index 0 upward); the DB triggers enforce range-against-
        manifest and, at commit, a hole-free 0..k prefix.
        """
        blob_id: int = await self.conn.fetchval(
            (
                "INSERT INTO data_blobs ("
                "  user_id, file_id, file_blob_index, file_start, file_end,"
                "  embedding_blob, abstract"
                ") VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING blob_id"
            ),
            user_id,
            file_id,
            file_blob_index,
            file_start,
            file_end,
            embedding_blob,
            abstract,
        )
        return blob_id

    async def fetch_for_file(self, file_id: int) -> list[DataBlobsModel]:
        """All blobs of a file, ordered by file_blob_index. Used to resume
        extraction (highest index present), seed the running_summary chain
        (last blob's abstract), and detect content drift (compare each
        blob's file_start/file_end against the recomputed chunk).
        """
        rows = await self.conn.fetch(
            f"SELECT {SELECT_COLUMNS} FROM data_blobs "
            "WHERE file_id = $1 ORDER BY file_blob_index",
            file_id,
        )
        return [DataBlobsModel.model_validate(dict(r)) for r in rows]

    async def fetch_embedding_blobs(
        self, file_id: int
    ) -> list[tuple[int, NDArray[np.float32]]]:
        """(blob_id, embedding_blob) for every blob of a file, ordered by
        index. The input to the file-relative embedding computation.
        """
        rows = await self.conn.fetch(
            "SELECT blob_id, embedding_blob FROM data_blobs "
            "WHERE file_id = $1 ORDER BY file_blob_index",
            file_id,
        )
        return [
            (r["blob_id"], np.asarray(r["embedding_blob"], dtype=np.float32))
            for r in rows
        ]
