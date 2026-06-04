from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from librarian.db.table import Table, TableModel


class DataBlobFileEmbeddingsModel(TableModel):
    blob_id: int
    file_id: int
    user_id: int
    embedding_with_file: NDArray[np.float32]
    created_at: datetime

    model_config = {"arbitrary_types_allowed": True}


class DataBlobFileEmbeddings(Table):
    async def insert_many(
        self,
        user_id: int,
        file_id: int,
        items: list[tuple[int, NDArray[np.float32]]],
    ) -> None:
        """Insert the file-relative embeddings for every blob of a file in
        one go. `items` is (blob_id, embedding_with_file). The caller runs
        this inside a single transaction so the whole set lands atomically —
        the deferred all-or-none trigger checks the set at commit.
        """
        if not items:
            return
        await self.conn.executemany(
            (
                "INSERT INTO data_blob_file_embeddings ("
                "  blob_id, file_id, user_id, embedding_with_file"
                ") VALUES ($1, $2, $3, $4)"
            ),
            [(blob_id, file_id, user_id, emb) for blob_id, emb in items],
        )

    async def exists_for_file(self, file_id: int) -> bool:
        """True once the file is fully processed: a row here only ever
        exists as part of a complete set (enforced by the all-or-none
        trigger), so one is sufficient proof.
        """
        return bool(
            await self.conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM data_blob_file_embeddings "
                "WHERE file_id = $1)",
                file_id,
            )
        )
