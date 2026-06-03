import logging

from pydantic import BaseModel
from pydantic_ai import ModelRetry, RunContext

from librarian.db.tree_children import (
    InvalidNodeRefError,
    NodeRow,
    fetch_children_scored,
    fetch_node_abstract,
    fetch_node_row,
    parse_node_ref,
)
from librarian.service.retrieval.deps import QueryDeps
from librarian.service.retrieval.events import Brief, ProgressEvent
from librarian.service.retrieval.projection import abstract_tags, abstract_title
from librarian.service.retrieval.tools.errors import BudgetExceededError
from librarian.service.retrieval.views import ChildSummary, child_summary

logger = logging.getLogger(__name__)


class ExpandedChildren(BaseModel):
    """One entry of `list_children`'s output: the parent ref plus its immediate
    children as summary views (title, tags, short fields, similarity score).
    Long prose is omitted — fetch it with `node_detail` if a child looks worth
    a closer look.
    """

    parent_ref: str
    children: list[ChildSummary]


async def list_children_impl(
    ctx: RunContext[QueryDeps],
    node_refs: list[str],
) -> list[ExpandedChildren]:
    """List the immediate children of each node referenced by `node_refs`.
    Children of a height>0 node are nodes; children of a height-0 node are
    blobs. Each child comes back as a *summary* — title, tags, topical/entity
    labels, and a sibling similarity score — enough to decide where to descend.
    Use `node_detail` for a node's prose, `peek_blob` to read a blob's text.

    Refs are the `ref` field on each child entry — strings like "n:172". Pass
    them verbatim; raw integers and `b:` refs are rejected. Counts as one
    "step" against the descent budget regardless of batch size.
    """
    deps = ctx.deps
    if deps.step_count >= deps.budget:
        raise BudgetExceededError(
            f"descent budget of {deps.budget} list_children calls exhausted"
        )
    if len(node_refs) == 0:
        raise ModelRetry("list_children requires at least one node ref")
    if len(node_refs) > deps.settings.tool_node_id_max_count:
        raise ModelRetry(
            f"list_children accepts at most "
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

    expanded: list[ExpandedChildren] = []
    briefs: list[Brief] = []
    for node, ref in zip(nodes, node_refs, strict=True):
        children = await fetch_children_scored(
            deps.conn, deps.user_id, node, deps.search_embedding
        )
        expanded.append(
            ExpandedChildren(
                parent_ref=ref,
                children=[child_summary(c) for c in children],
            )
        )
        abstract = await fetch_node_abstract(deps.conn, deps.user_id, node.node_id)
        briefs.append(
            Brief(title=abstract_title(abstract), tags=abstract_tags(abstract))
        )

    deps.step_count += 1

    logger.info(
        "retrieval: user %s step %d/%d list_children(%s)",
        deps.user_id,
        deps.step_count,
        deps.budget,
        node_refs,
    )

    if deps.emit is not None:
        await deps.emit(
            ProgressEvent(
                action="descend",
                items=briefs,
                step=deps.step_count,
                budget=deps.budget,
            )
        )

    return expanded
