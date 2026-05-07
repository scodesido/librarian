from datetime import datetime
from typing import Literal

from librarian.api.core.db.table import Table, TableModel

FileSource = Literal["GDRIVE"]
FileType = Literal["PDF", "TEXT", "OTHER"]
FileState = Literal["PENDING", "READY"]


class DataFilesModel(TableModel):
    file_id: int
    user_id: int
    path: str
    source: FileSource
    type: FileType
    state: FileState
    created_at: datetime
    updated_at: datetime


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
        counts: dict[FileState, int] = {"PENDING": 0, "READY": 0}
        for row in rows:
            counts[row["state"]] = row["n"]
        return counts
