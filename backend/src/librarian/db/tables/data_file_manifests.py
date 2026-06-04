from datetime import datetime

from librarian.db.table import Table, TableModel

SELECT_COLUMNS = (
    "file_id, user_id, expected_blob_count, page_count, char_count, "
    "byte_size, content_hash, created_at"
)


class DataFileManifestsModel(TableModel):
    file_id: int
    user_id: int
    expected_blob_count: int
    page_count: int | None
    char_count: int | None
    byte_size: int | None
    content_hash: str | None
    created_at: datetime


class DataFileManifests(Table):
    async def insert(
        self,
        user_id: int,
        file_id: int,
        expected_blob_count: int,
        page_count: int | None = None,
        char_count: int | None = None,
        byte_size: int | None = None,
        content_hash: str | None = None,
    ) -> None:
        """Write the manifest — the first step of processing a file, before
        any blob. expected_blob_count is the authoritative denominator the
        completeness triggers and the progress UI key on.
        """
        await self.conn.execute(
            (
                "INSERT INTO data_file_manifests ("
                "  file_id, user_id, expected_blob_count, page_count,"
                "  char_count, byte_size, content_hash"
                ") VALUES ($1, $2, $3, $4, $5, $6, $7)"
            ),
            file_id,
            user_id,
            expected_blob_count,
            page_count,
            char_count,
            byte_size,
            content_hash,
        )

    async def fetch(self, file_id: int) -> DataFileManifestsModel | None:
        record = await self.conn.fetchrow(
            f"SELECT {SELECT_COLUMNS} FROM data_file_manifests WHERE file_id = $1",
            file_id,
        )
        return DataFileManifestsModel.from_record(record)

    async def delete(self, file_id: int) -> None:
        """Invalidate a file's blob set: cascades to data_blobs and their
        file embeddings, leaving the data_files row for re-extraction.
        """
        await self.conn.execute(
            "DELETE FROM data_file_manifests WHERE file_id = $1", file_id
        )
