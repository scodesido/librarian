from asyncpg.pool import PoolConnectionProxy
from pydantic import BaseModel

from librarian.db.tables.data_files import SELECT_COLUMNS, DataFilesModel


class PipelineCounts(BaseModel):
    files_total: int
    files_ready: int
    blobs_total: int
    blobs_in_tree: int
    nodes_total: int
    nodes_weighted: int
    nodes_abstracted: int


async def claim_next_unready_file(
    conn: PoolConnectionProxy,
) -> DataFilesModel | None:
    record = await conn.fetchrow(
        (
            f"SELECT {SELECT_COLUMNS} FROM data_files f "
            "WHERE f.type IN ('PDF', 'TEXT') "
            "  AND NOT EXISTS ("
            "    SELECT 1 FROM data_blobs b "
            "    WHERE b.file_id = f.file_id AND b.is_final_blob"
            "  ) "
            "ORDER BY f.created_at "
            "LIMIT 1 "
            "FOR UPDATE SKIP LOCKED"
        ),
    )
    return DataFilesModel.from_record(record)


async def count_user_pipeline(
    conn: PoolConnectionProxy, user_id: int
) -> PipelineCounts:
    row = await conn.fetchrow(
        (
            "SELECT "
            "  (SELECT count(*) FROM data_files WHERE user_id = $1) AS files_total, "
            "  (SELECT count(*) FROM data_files f WHERE f.user_id = $1 AND ("
            "      f.type = 'OTHER' OR EXISTS ("
            "        SELECT 1 FROM data_blobs b "
            "        WHERE b.file_id = f.file_id AND b.is_final_blob"
            "      )"
            "  )) AS files_ready, "
            "  (SELECT count(*) FROM data_blobs WHERE user_id = $1) AS blobs_total, "
            "  (SELECT count(*) FROM data_blob_edges WHERE user_id = $1) AS blobs_in_tree, "
            "  (SELECT count(*) FROM data_nodes WHERE user_id = $1) AS nodes_total, "
            "  (SELECT count(*) FROM data_node_weights WHERE user_id = $1) AS nodes_weighted, "
            "  (SELECT count(*) FROM data_node_abstracts WHERE user_id = $1) AS nodes_abstracted"
        ),
        user_id,
    )
    assert row is not None
    return PipelineCounts(
        files_total=row["files_total"],
        files_ready=row["files_ready"],
        blobs_total=row["blobs_total"],
        blobs_in_tree=row["blobs_in_tree"],
        nodes_total=row["nodes_total"],
        nodes_weighted=row["nodes_weighted"],
        nodes_abstracted=row["nodes_abstracted"],
    )
