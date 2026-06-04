import logging
from typing import Any

from pydantic import BaseModel
from pydantic_ai import ModelRetry, RunContext

from librarian.db.tree_children import (
    InvalidBlobRefError,
    fetch_blob_abstract,
    parse_blob_ref,
)
from librarian.service.retrieval.deps import QueryDeps
from librarian.service.retrieval.events import Brief, ProgressEvent
from librarian.service.retrieval.projection import (
    abstract_tags,
    abstract_title,
    detail_abstract,
)
from librarian.service.retrieval.provenance import ensure_refs_seen

logger = logging.getLogger(__name__)


class BlobDetail(BaseModel):
    """`blob_detail`'s output: the detail projection of one blob's Abstract —
    the prose (summary, key_questions, key_claims, running_summary) that the
    `list_children` / `list_file_blobs` summaries deliberately omit. The blob
    analogue of `NodeDetail`.
    """

    ref: str
    detail: dict[str, Any]


async def blob_detail_impl(
    ctx: RunContext[QueryDeps],
    blob_ref: str,
) -> BlobDetail:
    """Fetch the detailed Abstract fields of one blob — its prose summary, key
    questions/claims, and running summary — that the summary listings leave out.
    This is the cheap way to inspect a blob: prefer it over `peek_blob` for
    triage, and reserve `peek_blob` (which reads the full raw text) for
    confirming the handful of candidates you've already narrowed down.

    Pass the blob's `ref` (a string like "b:455") verbatim. Does not count
    against the descent budget but is capped at `max_blob_detail_fetches` calls
    per query.
    """
    deps = ctx.deps
    if deps.blob_detail_fetch_count >= deps.settings.max_blob_detail_fetches:
        raise ModelRetry(
            f"reached the cap of {deps.settings.max_blob_detail_fetches} "
            "blob_detail fetches; work with the summaries you have"
        )
    try:
        blob_id = parse_blob_ref(blob_ref)
    except InvalidBlobRefError as exc:
        raise ModelRetry(str(exc)) from exc

    ensure_refs_seen(deps, [blob_ref])

    async with deps.db_lock:
        abstract = await fetch_blob_abstract(deps.conn, deps.user_id, blob_id)
    if abstract is None:
        raise ModelRetry(f"blob ref {blob_ref!r} does not match any blob for this user")
    deps.blob_detail_fetch_count += 1

    logger.info("retrieval: user %s blob_detail(%s)", deps.user_id, blob_ref)

    if deps.emit is not None:
        await deps.emit(
            ProgressEvent(
                action="blob_detail",
                items=[
                    Brief(title=abstract_title(abstract), tags=abstract_tags(abstract))
                ],
            )
        )

    return BlobDetail(ref=blob_ref, detail=detail_abstract(abstract))
