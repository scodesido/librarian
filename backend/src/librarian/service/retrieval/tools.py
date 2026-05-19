import logging
from typing import Any

from pydantic_ai import ModelRetry, RunContext

from librarian.db.tables.data_files import FileSource, FileType
from librarian.db.tree_children import (
    InvalidBlobRefError,
    InvalidNodeRefError,
    NodeRow,
    fetch_children,
    fetch_node_row,
    parse_blob_ref,
    parse_node_ref,
)
from librarian.service.retrieval.deps import QueryDeps
from librarian.service.retrieval.events import (
    BlobResult,
    ExpandedNode,
    ExpandEvent,
    FetchEvent,
)
from librarian.service.retrieval.providers import BlobLocator

logger = logging.getLogger(__name__)


class BudgetExceededError(Exception):
    """The agent tried to descend past its budget. Propagates out of
    `agent.run` so the endpoint can return a 400 — the spec is explicit
    that this is a client-facing error, not something to recover from.
    """


class UnknownBlobIdsError(Exception):
    """Raised by `resolve_blob_results` when one or more requested blob_ids
    don't exist for the user. Wrapped into `ModelRetry` by the in-loop
    tool; surfaced as 500 by the endpoint (since the final-answer path
    shouldn't see this in normal operation).
    """

    def __init__(self, missing: list[int]) -> None:
        super().__init__(
            f"blob_id(s) {missing} do not exist or do not belong to this user"
        )
        self.missing = missing


async def expand_nodes_impl(
    ctx: RunContext[QueryDeps],
    node_refs: list[str],
) -> list[ExpandedNode]:
    """Fetch the immediate children of each node referenced by `node_refs`.
    Children of a height>0 node are nodes (with abstracts and blob counts);
    children of a height-0 node are blobs. The agent uses the returned
    abstracts to decide where to descend next.

    Refs are the `ref` field on each child entry — strings like "n:172".
    Pass them verbatim. The prefix is what distinguishes a node ref from a
    blob ref; raw integers are rejected.

    Counts as one "step" against the descent budget regardless of how many
    refs are in the batch.
    """
    deps = ctx.deps
    if deps.step_count >= deps.budget:
        # Hard stop: spec says a budget-exhausted run is a 400 to the client,
        # so we propagate this past the agent loop entirely.
        raise BudgetExceededError(
            f"descent budget of {deps.budget} expand_nodes calls exhausted"
        )
    if len(node_refs) == 0:
        raise ModelRetry("expand_nodes requires at least one node ref")
    if len(node_refs) > deps.settings.tool_node_id_max_count:
        raise ModelRetry(
            f"expand_nodes accepts at most "
            f"{deps.settings.tool_node_id_max_count} node refs per call; "
            f"got {len(node_refs)}"
        )

    node_ids: list[int] = []
    for ref in node_refs:
        try:
            node_ids.append(parse_node_ref(ref))
        except InvalidNodeRefError as exc:
            raise ModelRetry(str(exc)) from exc

    nodes: list[NodeRow] = []
    for nid, ref in zip(node_ids, node_refs, strict=True):
        row = await fetch_node_row(deps.conn, deps.user_id, nid)
        if row is None:
            raise ModelRetry(f"node ref {ref!r} does not match any node for this user")
        nodes.append(row)

    expanded: list[ExpandedNode] = []
    for node in nodes:
        children = await fetch_children(deps.conn, deps.user_id, node)
        expanded.append(ExpandedNode(node_id=node.node_id, children=children))

    deps.step_count += 1
    for nid in node_ids:
        if nid not in deps.visited_node_ids:
            deps.visited_node_ids.append(nid)

    logger.info(
        "retrieval: user %s step %d/%d expand_nodes(%s)",
        deps.user_id,
        deps.step_count,
        deps.budget,
        node_refs,
    )

    if deps.emit is not None:
        await deps.emit(
            ExpandEvent(
                step=deps.step_count,
                budget=deps.budget,
                requested_node_ids=list(node_ids),
                expanded=expanded,
            )
        )

    return expanded


async def fetch_blob_contents_impl(
    ctx: RunContext[QueryDeps],
    blob_refs: list[str],
) -> list[BlobResult]:
    """Fetch the plaintext contents of one or more blobs (and their abstracts,
    so the agent can confirm them in-band). Does NOT count against the descent
    budget, but is capped separately by `max_blob_content_fetches` total calls.

    Refs are the `ref` field on each blob child entry — strings like "b:455".
    Pass them verbatim. Node refs (`n:...`) are rejected with a diagnostic;
    raw integers are also rejected.

    The agent uses this to peek at candidates before committing to a final
    selection. The endpoint will re-resolve the final selection through the
    same provider after the agent finishes — the per-request download cache
    makes the duplicate cheap.
    """
    deps = ctx.deps
    if len(blob_refs) == 0:
        raise ModelRetry("fetch_blob_contents requires at least one blob ref")
    if len(blob_refs) > deps.settings.max_returned_blobs:
        raise ModelRetry(
            f"fetch_blob_contents accepts at most "
            f"{deps.settings.max_returned_blobs} blob refs per call; "
            f"got {len(blob_refs)}"
        )
    if deps.content_fetch_count >= deps.settings.max_blob_content_fetches:
        # Not a hard endpoint error — recoverable: tell the agent to stop
        # peeking and emit its FinalAnswer.
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

    try:
        results = await resolve_blob_results(deps, blob_ids)
    except UnknownBlobIdsError as exc:
        raise ModelRetry(str(exc)) from exc
    if deps.emit is not None:
        await deps.emit(FetchEvent(blob_ids=list(blob_ids)))
    return results


async def resolve_blob_results(
    deps: QueryDeps,
    blob_ids: list[int],
) -> list[BlobResult]:
    """Load blob rows + their owning file, then materialise plaintext via
    the provider. Shared by the in-loop tool and the endpoint's final-answer
    assembly. Order of the result follows the input order.
    """
    rows = await deps.conn.fetch(
        """
        SELECT b.blob_id, b.file_id, b.file_start, b.file_end, b.abstract,
               f.path AS source_path, f.source, f.type
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

    results: list[BlobResult] = []
    for bid in blob_ids:
        r = by_id[bid]
        source: FileSource = r["source"]
        type_: FileType = r["type"]
        locator = BlobLocator(
            file_id=r["file_id"],
            source=source,
            source_path=r["source_path"],
            type=type_,
            file_start=r["file_start"],
            file_end=r["file_end"],
        )
        content = await deps.provider.fetch_text(locator)
        results.append(
            BlobResult(
                blob_id=r["blob_id"],
                file_id=r["file_id"],
                file_path=r["source_path"],
                file_start=r["file_start"],
                file_end=r["file_end"],
                abstract=r["abstract"],
                content=content,
            )
        )
    return results
