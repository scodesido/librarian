from datetime import datetime, timedelta
from typing import Literal

from librarian.db.table import Table, TableModel

FileSource = Literal["GDRIVE"]
FileType = Literal["PDF", "TEXT", "OTHER"]
FileState = Literal["PENDING", "PROCESSING", "READY", "FAILED"]


class DataFilesModel(TableModel):
    file_id: int
    user_id: int
    path: str
    source: FileSource
    type: FileType
    state: FileState
    created_at: datetime
    updated_at: datetime


SELECT_COLUMNS = "file_id, user_id, path, source, type, state, created_at, updated_at"


class DataFiles(Table):
    async def insert_missing(
        self,
        user_id: int,
        source: FileSource,
        items: list[tuple[str, FileType]],
    ) -> int:
        if not items:
            return 0
        paths = [path for path, _ in items]
        types = [type_ for _, type_ in items]
        result: str = await self.conn.execute(
            (
                "INSERT INTO data_files (user_id, source, path, type, state) "
                "SELECT $1, $2, p.path, p.type, 'PENDING' "
                "FROM unnest($3::text[], $4::text[]) AS p(path, type) "
                "ON CONFLICT (user_id, source, path) DO NOTHING"
            ),
            user_id,
            source,
            paths,
            types,
        )
        return int(result.rsplit(" ", 1)[-1])

    async def delete_missing(
        self,
        user_id: int,
        source: FileSource,
        keep_paths: list[str],
    ) -> int:
        result: str = await self.conn.execute(
            (
                "DELETE FROM data_files "
                "WHERE user_id = $1 AND source = $2 AND NOT (path = ANY($3))"
            ),
            user_id,
            source,
            keep_paths,
        )
        return int(result.rsplit(" ", 1)[-1])

    async def count_by_state(self, user_id: int) -> dict[FileState, int]:
        rows = await self.conn.fetch(
            "SELECT state, count(*) AS n FROM data_files "
            "WHERE user_id = $1 GROUP BY state",
            user_id,
        )
        counts: dict[FileState, int] = {
            "PENDING": 0,
            "PROCESSING": 0,
            "READY": 0,
            "FAILED": 0,
        }
        for row in rows:
            counts[row["state"]] = row["n"]
        return counts

    async def claim_next_pending(self) -> DataFilesModel | None:
        record = await self.conn.fetchrow(
            (
                "UPDATE data_files SET state = 'PROCESSING' "
                "WHERE file_id = ("
                "    SELECT file_id FROM data_files "
                "    WHERE state = 'PENDING' "
                "    ORDER BY created_at "
                "    LIMIT 1 "
                "    FOR UPDATE SKIP LOCKED"
                ") "
                f"RETURNING {SELECT_COLUMNS}"
            ),
        )
        return DataFilesModel.from_record(record)

    async def mark_ready(self, file_id: int) -> None:
        await self.conn.execute(
            "UPDATE data_files SET state = 'READY' WHERE file_id = $1",
            file_id,
        )

    async def mark_failed(self, file_id: int) -> None:
        await self.conn.execute(
            "UPDATE data_files SET state = 'FAILED' WHERE file_id = $1",
            file_id,
        )

    async def sweep_stale_processing(self, older_than: timedelta) -> int:
        result: str = await self.conn.execute(
            (
                "UPDATE data_files SET state = 'PENDING' "
                "WHERE state = 'PROCESSING' AND updated_at < now() - $1::interval"
            ),
            older_than,
        )
        return int(result.rsplit(" ", 1)[-1])
