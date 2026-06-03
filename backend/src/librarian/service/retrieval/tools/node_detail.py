import logging
from typing import Any

from pydantic import BaseModel
from pydantic_ai import ModelRetry, RunContext

from librarian.db.tree_children import (
    InvalidNodeRefError,
    fetch_node_abstract,
    parse_node_ref,
)
from librarian.service.retrieval.deps import QueryDeps
from librarian.service.retrieval.events import Brief, ProgressEvent
from librarian.service.retrieval.projection import (
    abstract_tags,
    abstract_title,
    detail_abstract,
)

logger = logging.getLogger(__name__)


class NodeDetail(BaseModel):
    """`node_detail`'s output: the detail projection of one node's Abstract —
    the prose (summary, key_questions, key_claims) that `list_children`
    deliberately omits.
    """

    ref: str
    detail: dict[str, Any]


async def node_detail_impl(
    ctx: RunContext[QueryDeps],
    node_ref: str,
) -> NodeDetail:
    """Fetch the detailed Abstract fields of one node — its prose summary and
    key questions/claims — that the `list_children` summary leaves out. Use
    this when a node's summary looks promising and you want the fuller picture
    before deciding whether to descend.

    Pass the node's `ref` (a string like "n:172") verbatim. Does not count
    against the descent budget but is capped at
    `max_node_detail_fetches` calls per query.
    """
    deps = ctx.deps
    if deps.detail_fetch_count >= deps.settings.max_node_detail_fetches:
        raise ModelRetry(
            f"reached the cap of {deps.settings.max_node_detail_fetches} "
            "node_detail fetches; work with the summaries you have"
        )
    try:
        node_id = parse_node_ref(node_ref)
    except InvalidNodeRefError as exc:
        raise ModelRetry(str(exc)) from exc

    abstract = await fetch_node_abstract(deps.conn, deps.user_id, node_id)
    if abstract is None:
        raise ModelRetry(
            f"node ref {node_ref!r} does not match any node with an abstract "
            "for this user"
        )
    deps.detail_fetch_count += 1

    logger.info("retrieval: user %s node_detail(%s)", deps.user_id, node_ref)

    if deps.emit is not None:
        await deps.emit(
            ProgressEvent(
                action="detail",
                items=[
                    Brief(title=abstract_title(abstract), tags=abstract_tags(abstract))
                ],
            )
        )

    return NodeDetail(ref=node_ref, detail=detail_abstract(abstract))
