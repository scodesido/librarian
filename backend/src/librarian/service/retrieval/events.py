from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class TermsEvent(BaseModel):
    """Emitted once at the start of the SSE stream (before the first
    `ProgressEvent`). Carries the string we actually embedded for similarity
    scoring, plus a flag indicating whether it came from an explicit
    `search_terms` / the question itself (`extracted=False`) or from the
    pre-flight extraction agent (`extracted=True`).

    The FE renders this immediately so the user can see what we searched for
    without waiting for `done`. The same string is echoed on
    `DoneEvent.effective_search_terms` for non-streaming clients.
    """

    kind: Literal["terms"] = "terms"
    effective_search_terms: str
    extracted: bool


class Brief(BaseModel):
    """The whole of what we expose about a node/blob the agent touched mid-walk:
    a display title and the flat tag list. No ids, no scores, no extraction
    fields — those are internals we keep free to iterate on.
    """

    title: str | None
    tags: list[str]


class ProgressEvent(BaseModel):
    """One per agent tool call. `action` says which tool fired; `items` carries
    the title+tags of whatever it touched. `step`/`budget` are populated only
    on `descend` (the only action that consumes the descent budget) so a
    progress bar can move; everything else leaves them None.
    """

    kind: Literal["progress"] = "progress"
    action: Literal["descend", "detail", "peek", "file"]
    items: list[Brief]
    step: int | None = None
    budget: int | None = None


class ResultBlob(BaseModel):
    """Final per-blob payload. `content` is plaintext when `encoding == "text"`
    and base64 when `encoding == "base64"` (binary mode); `mime_type` describes
    it either way. Deliberately free of internal ids, byte ranges, and the full
    Abstract — just what a caller needs to use the fragment.
    """

    title: str | None
    file_name: str
    tags: list[str]
    mime_type: str
    content: str
    encoding: Literal["text", "base64"]


class DoneEvent(BaseModel):
    kind: Literal["done"] = "done"
    rationale: str
    # The search-terms string actually used (echoed from TermsEvent so JSON
    # callers and stream clients that only read the final event have it).
    effective_search_terms: str
    blobs: list[ResultBlob]


class ErrorEvent(BaseModel):
    kind: Literal["error"] = "error"
    detail: str


QueryEvent = Annotated[
    Union[TermsEvent, ProgressEvent, DoneEvent, ErrorEvent],
    Field(discriminator="kind"),
]
