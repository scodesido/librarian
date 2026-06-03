"""Blob row loading shared by the in-loop `peek_blob` tool and the final-answer
assembly, plus the final-result resolver that materialises content in the
caller's chosen format (plaintext or base64 bytes).
"""

import base64
from dataclasses import dataclass
from typing import Any

from librarian.db.tables.data_files import FileSource, FileType
from librarian.service.retrieval.deps import QueryDeps
from librarian.service.retrieval.events import ResultBlob
from librarian.service.retrieval.projection import abstract_tags, abstract_title
from librarian.service.retrieval.providers import BlobLocator
from librarian.service.retrieval.tools.errors import UnknownBlobIdsError


@dataclass
class LoadedBlob:
    """A blob row resolved to everything we need to materialise it: a provider
    locator, the stored Abstract (for title/tags projection), and the source
    file path.
    """

    locator: BlobLocator
    abstract: dict[str, Any]
    file_name: str


async def load_blobs(deps: QueryDeps, blob_ids: list[int]) -> list[LoadedBlob]:
    """Load blob rows + their owning file in the input order. Raises
    UnknownBlobIdsError if any id is missing for this user.
    """
    rows = await deps.conn.fetch(
        """
        SELECT b.blob_id, b.file_id, b.file_start, b.file_end, b.abstract,
               f.path AS source_path, f.name AS file_name, f.source, f.type
        FROM data_blobs b
        JOIN data_files f ON f.file_id = b.file_id
        WHERE b.user_id = $1 AND b.blob_id = ANY($2)
        """,
        deps.user_id,
        blob_ids,
    )
    by_id: dict[int, dict[str, Any]] = {r["blob_id"]: dict(r) for r in rows}
    missing = [bid for bid in blob_ids if bid not in by_id]
    if missing:
        raise UnknownBlobIdsError(missing)

    loaded: list[LoadedBlob] = []
    for bid in blob_ids:
        r = by_id[bid]
        source: FileSource = r["source"]
        type_: FileType = r["type"]
        loaded.append(
            LoadedBlob(
                locator=BlobLocator(
                    file_id=r["file_id"],
                    source=source,
                    source_path=r["source_path"],
                    type=type_,
                    file_start=r["file_start"],
                    file_end=r["file_end"],
                ),
                abstract=r["abstract"],
                file_name=r["file_name"],
            )
        )
    return loaded


async def resolve_result_blobs(
    deps: QueryDeps, blob_ids: list[int], binary: bool
) -> list[ResultBlob]:
    """Materialise the final selection into wire `ResultBlob`s. Text mode
    returns plaintext (`encoding="text"`); binary mode returns base64 bytes
    plus the provider's MIME type (`encoding="base64"`).
    """
    loaded = await load_blobs(deps, blob_ids)
    results: list[ResultBlob] = []
    for lb in loaded:
        title = abstract_title(lb.abstract)
        tags = abstract_tags(lb.abstract)
        if binary:
            data, mime = await deps.provider.fetch_bytes(lb.locator)
            results.append(
                ResultBlob(
                    title=title,
                    file_name=lb.file_name,
                    tags=tags,
                    mime_type=mime,
                    content=base64.b64encode(data).decode("ascii"),
                    encoding="base64",
                )
            )
        else:
            text = await deps.provider.fetch_text(lb.locator)
            results.append(
                ResultBlob(
                    title=title,
                    file_name=lb.file_name,
                    tags=tags,
                    mime_type="text/plain",
                    content=text,
                    encoding="text",
                )
            )
    return results
