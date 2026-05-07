from datetime import datetime

from librarian.db.table import Table, TableModel


class DataBlobsModel(TableModel):
    blob_id: int
    file_id: int
    start: int
    end: int
    created_at: datetime
    updated_at: datetime


class DataBlobs(Table):
    async def create(self, file_id: int, start: int, end: int) -> int:
        blob_id: int = await self.conn.fetchval(
            (
                'INSERT INTO data_blobs (file_id, "start", "end") '
                "VALUES ($1, $2, $3) RETURNING blob_id"
            ),
            file_id,
            start,
            end,
        )
        return blob_id

    async def delete_for_file(self, file_id: int) -> int:
        result: str = await self.conn.execute(
            "DELETE FROM data_blobs WHERE file_id = $1",
            file_id,
        )
        return int(result.rsplit(" ", 1)[-1])
