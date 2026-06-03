from datetime import datetime
from typing import Literal

from librarian.db.table import Table, TableModel

FileSource = Literal["GDRIVE"]
FileType = Literal["PDF", "TEXT", "OTHER"]


class DataFilesModel(TableModel):
    file_id: int
    user_id: int
    path: str
    source: FileSource
    type: FileType
    source_modified_at: datetime | None
    created_at: datetime


SELECT_COLUMNS = "file_id, user_id, path, source, type, source_modified_at, created_at"


class DataFiles(Table):
    async def insert_missing(
        self,
        user_id: int,
        source: FileSource,
        items: list[tuple[str, FileType, str]],
    ) -> int:
        # TODO: also populate source_modified_at from the sync layer and add
        # a stale-detection branch ("source row is newer than DB row -> delete
        # + re-insert, cascading blobs"). Deferred until the sync rewrite.
        #
        # `items` is (path, type, name): `path` is the source key (Drive file
        # id), `name` the human-readable full path captured at sync. ON
        # CONFLICT DO NOTHING means an already-synced file keeps its existing
        # `name` — pre-migration rows stay '' until cleared and re-synced.
        if not items:
            return 0
        paths = [path for path, _, _ in items]
        types = [type_ for _, type_, _ in items]
        names = [name for _, _, name in items]
        result: str = await self.conn.execute(
            (
                "INSERT INTO data_files (user_id, source, path, type, name) "
                "SELECT $1, $2, p.path, p.type, p.name "
                "FROM unnest($3::text[], $4::text[], $5::text[]) "
                "AS p(path, type, name) "
                "ON CONFLICT (user_id, source, path) DO NOTHING"
            ),
            user_id,
            source,
            paths,
            types,
            names,
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
