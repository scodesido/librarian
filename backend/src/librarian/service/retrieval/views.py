"""Agent-facing summary views shared by `list_children`, `list_file_blobs`,
and the instructions seed. They mirror the db-layer `NodeChildView` /
`BlobChildView` but carry only the *summary* projection of the Abstract
(see `projection.py`) — never the long prose. The agent reaches for
`node_detail` / `peek_blob` when it wants more.

The integer `node_id` / `blob_id` survive for log readability; the agent is
told (in its instructions) to pass `ref` to tools and never the integers.
"""

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field

from librarian.db.tree_children import BlobChildView, NodeChildView
from librarian.service.retrieval.projection import summary_abstract


class NodeSummary(BaseModel):
    kind: Literal["node"] = "node"
    ref: str
    node_id: int
    height: int
    blob_count: int | None
    similarity_score: float | None = None
    # Summary projection of the node's Abstract — short fields + tags only.
    abstract: dict[str, Any]


class BlobSummary(BaseModel):
    kind: Literal["blob"] = "blob"
    ref: str
    blob_id: int
    file_id: int
    file_blob_index: int
    similarity_score: float | None = None
    # Summary projection of the blob's Abstract.
    abstract: dict[str, Any]


ChildSummary = Annotated[Union[NodeSummary, BlobSummary], Field(discriminator="kind")]


def node_summary(view: NodeChildView) -> NodeSummary:
    return NodeSummary(
        ref=view.ref,
        node_id=view.node_id,
        height=view.height,
        blob_count=view.blob_count,
        similarity_score=view.similarity_score,
        abstract=summary_abstract(view.abstract),
    )


def blob_summary(view: BlobChildView) -> BlobSummary:
    return BlobSummary(
        ref=view.ref,
        blob_id=view.blob_id,
        file_id=view.file_id,
        file_blob_index=view.file_blob_index,
        similarity_score=view.similarity_score,
        abstract=summary_abstract(view.abstract),
    )


def child_summary(view: NodeChildView | BlobChildView) -> ChildSummary:
    if isinstance(view, NodeChildView):
        return node_summary(view)
    return blob_summary(view)
