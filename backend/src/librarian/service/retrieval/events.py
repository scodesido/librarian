from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field

from librarian.db.tree_children import ChildView


class ExpandEvent(BaseModel):
    """The agent called `expand_nodes` with a batch of node_ids. Carries the
    full result so the FE can render one timeline entry per call.
    """

    kind: Literal["expand"] = "expand"
    step: int
    budget: int
    requested_node_ids: list[int]
    expanded: list["ExpandedNode"]


class FetchEvent(BaseModel):
    """The agent peeked at blob contents. We don't stream the contents
    themselves (they may be large); just the blob_ids it looked at.
    """

    kind: Literal["fetch"] = "fetch"
    blob_ids: list[int]


class DoneEvent(BaseModel):
    kind: Literal["done"] = "done"
    blobs: list["BlobResult"]
    visited_node_ids: list[int]
    steps: int
    rationale: str


class ErrorEvent(BaseModel):
    kind: Literal["error"] = "error"
    detail: str


QueryEvent = Annotated[
    Union[ExpandEvent, FetchEvent, DoneEvent, ErrorEvent],
    Field(discriminator="kind"),
]


class ExpandedNode(BaseModel):
    """One entry of the `expand_nodes` tool's structured output: the parent
    node_id plus its immediate children, each carrying the abstract the agent
    needs to choose where to descend next.
    """

    node_id: int
    children: list[ChildView]


class BlobResult(BaseModel):
    """Final per-blob payload returned in the response (or the `done` event).
    `content` is plaintext; binary support is a future extension.
    """

    blob_id: int
    file_id: int
    file_path: str
    file_start: int
    file_end: int
    abstract: dict[str, Any]
    content: str


ExpandEvent.model_rebuild()
DoneEvent.model_rebuild()
