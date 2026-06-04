from asyncpg.pool import PoolConnectionProxy
from pydantic import BaseModel


class PipelineCounts(BaseModel):
    files_total: int
    files_ready: int
    # Blob-abstraction progress. blobs_expected is the sum of the manifests'
    # expected_blob_count (a lower bound while files are still being
    # manifested); blobs_total is how many blobs have actually been created
    # so far; blobs_file_embedded is how many have their file-relative
    # embedding (the step that marks a file ready).
    blobs_expected: int
    blobs_total: int
    blobs_file_embedded: int
    blobs_in_tree: int
    nodes_total: int
    nodes_weighted: int
    nodes_abstracted: int


async def count_user_pipeline(
    conn: PoolConnectionProxy, user_id: int
) -> PipelineCounts:
    row = await conn.fetchrow(
        (
            "SELECT "
            "  (SELECT count(*) FROM data_files WHERE user_id = $1) AS files_total, "
            "  (SELECT count(*) FROM data_files f WHERE f.user_id = $1 AND ("
            "      f.type = 'OTHER' OR EXISTS ("
            "        SELECT 1 FROM data_blob_file_embeddings e "
            "        WHERE e.file_id = f.file_id"
            "      )"
            "  )) AS files_ready, "
            "  (SELECT COALESCE(sum(expected_blob_count), 0) "
            "     FROM data_file_manifests WHERE user_id = $1) AS blobs_expected, "
            "  (SELECT count(*) FROM data_blobs WHERE user_id = $1) AS blobs_total, "
            "  (SELECT count(*) FROM data_blob_file_embeddings WHERE user_id = $1) "
            "     AS blobs_file_embedded, "
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
        blobs_expected=row["blobs_expected"],
        blobs_total=row["blobs_total"],
        blobs_file_embedded=row["blobs_file_embedded"],
        blobs_in_tree=row["blobs_in_tree"],
        nodes_total=row["nodes_total"],
        nodes_weighted=row["nodes_weighted"],
        nodes_abstracted=row["nodes_abstracted"],
    )
