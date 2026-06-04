import logging

from pydantic import BaseModel
from pydantic_ai import ModelRetry, RunContext

from librarian.db.tree_children import InvalidBlobRefError, parse_blob_ref
from librarian.service.retrieval.deps import QueryDeps
from librarian.service.retrieval.events import Brief, ProgressEvent
from librarian.service.retrieval.projection import abstract_tags, abstract_title
from librarian.service.retrieval.provenance import ensure_refs_seen
from librarian.service.retrieval.resolve import load_blobs
from librarian.service.retrieval.tools.errors import UnknownBlobIdsError

logger = logging.getLogger(__name__)


class BlobPeek(BaseModel):
    """`peek_blob`'s per-blob output: the ref, a display title, and the
    plaintext content the agent reads to confirm relevance.
    """

    ref: str
    title: str | None
    content: str


async def peek_blob_impl(
    ctx: RunContext[QueryDeps],
    blob_refs: list[str],
) -> list[BlobPeek]:
    """Read the plaintext of one or more blobs to confirm relevance before
    committing to a final selection. Always returns text (even when the final
    answer is requested as binary).

    Refs are the `ref` field on each blob entry — strings like "b:455". Pass
    them verbatim; `n:` refs and raw integers are rejected. Does not count
    against the descent budget but is capped at `max_blob_content_fetches`
    total calls per query.
    """
    deps = ctx.deps
    if len(blob_refs) == 0:
        raise ModelRetry("peek_blob requires at least one blob ref")
    if len(blob_refs) > deps.settings.max_returned_blobs:
        raise ModelRetry(
            f"peek_blob accepts at most "
            f"{deps.settings.max_returned_blobs} blob refs per call; "
            f"got {len(blob_refs)}"
        )
    if deps.content_fetch_count >= deps.settings.max_blob_content_fetches:
        raise ModelRetry(
            f"reached the cap of {deps.settings.max_blob_content_fetches} "
            "blob-content fetches; emit your FinalAnswer now"
        )
    deps.content_fetch_count += 1

    blob_ids: list[int] = []
    for ref in blob_refs:
        try:
            blob_ids.append(parse_blob_ref(ref))
        except InvalidBlobRefError as exc:
            raise ModelRetry(str(exc)) from exc

    ensure_refs_seen(deps, blob_refs)

    try:
        async with deps.db_lock:
            loaded = await load_blobs(deps, blob_ids)
    except UnknownBlobIdsError as exc:
        raise ModelRetry(str(exc)) from exc

    results: list[BlobPeek] = []
    briefs: list[Brief] = []
    for ref, lb in zip(blob_refs, loaded, strict=True):
        content = await deps.provider.fetch_text(lb.locator)
        results.append(
            BlobPeek(ref=ref, title=abstract_title(lb.abstract), content=content)
        )
        briefs.append(
            Brief(title=abstract_title(lb.abstract), tags=abstract_tags(lb.abstract))
        )

    logger.info("retrieval: user %s peek_blob(%s)", deps.user_id, blob_refs)

    if deps.emit is not None:
        await deps.emit(ProgressEvent(action="peek", items=briefs))

    return results
