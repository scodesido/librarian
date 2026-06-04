import logging

from pydantic import BaseModel
from pydantic_ai import ModelRetry, RunContext

from librarian.db.tree_children import (
    InvalidBlobRefError,
    fetch_blob_file_id,
    fetch_file_blobs_scored,
    parse_blob_ref,
)
from librarian.service.retrieval.deps import QueryDeps
from librarian.service.retrieval.events import Brief, ProgressEvent
from librarian.service.retrieval.projection import abstract_tags, abstract_title
from librarian.service.retrieval.provenance import ensure_refs_seen, record_seen_refs
from librarian.service.retrieval.views import BlobSummary, blob_summary

logger = logging.getLogger(__name__)


class FileBlobsPage(BaseModel):
    """One page of `list_file_blobs`: the file's blobs in document order as
    summary views, plus pagination cursors. `next_offset` is the value to pass
    back for the following page, or None when the file is exhausted.
    """

    blobs: list[BlobSummary]
    offset: int
    total: int
    next_offset: int | None


async def list_file_blobs_impl(
    ctx: RunContext[QueryDeps],
    blob_ref: str,
    offset: int = 0,
) -> FileBlobsPage:
    """List the summary views of every blob in the *same source file* as the
    given blob, in document order. Use this after reaching a blob through tree
    descent when you want to see the rest of that document — sibling fragments
    that may live in unrelated parts of the tree.

    Pass the blob's `ref` (e.g. "b:455") verbatim. Results are paginated: each
    call returns up to a fixed page size; pass the returned `next_offset` to
    fetch the next page (None means there are no more). Does not count against
    the descent budget but is capped at `max_file_blob_listings` calls.
    """
    deps = ctx.deps
    if deps.file_listing_count >= deps.settings.max_file_blob_listings:
        raise ModelRetry(
            f"reached the cap of {deps.settings.max_file_blob_listings} "
            "list_file_blobs calls; work with what you have"
        )
    if offset < 0:
        raise ModelRetry("offset must be >= 0")
    try:
        blob_id = parse_blob_ref(blob_ref)
    except InvalidBlobRefError as exc:
        raise ModelRetry(str(exc)) from exc

    ensure_refs_seen(deps, [blob_ref])

    async with deps.db_lock:
        file_id = await fetch_blob_file_id(deps.conn, deps.user_id, blob_id)
    if file_id is None:
        raise ModelRetry(f"blob ref {blob_ref!r} does not match any blob for this user")
    deps.file_listing_count += 1

    page_size = deps.settings.file_blobs_page_size
    async with deps.db_lock:
        rows, total = await fetch_file_blobs_scored(
            deps.conn, deps.user_id, file_id, deps.search_embedding, page_size, offset
        )
    blobs = [blob_summary(r) for r in rows]
    record_seen_refs(deps, (b.ref for b in blobs))
    next_offset = offset + len(rows) if offset + len(rows) < total else None

    logger.info(
        "retrieval: user %s list_file_blobs(%s) file=%d offset=%d/%d",
        deps.user_id,
        blob_ref,
        file_id,
        offset,
        total,
    )

    if deps.emit is not None:
        briefs = [
            Brief(title=abstract_title(r.abstract), tags=abstract_tags(r.abstract))
            for r in rows
        ]
        await deps.emit(ProgressEvent(action="file", items=briefs))

    return FileBlobsPage(
        blobs=blobs, offset=offset, total=total, next_offset=next_offset
    )
