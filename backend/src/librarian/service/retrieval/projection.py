"""Two disjoint projections of an Abstract (`service/abstract.py`), plus
the helpers that read them off the stored JSONB dict.

`SUMMARY_FIELDS` are the cheap fields shown on every listing
(`list_children`, `list_file_blobs`, the instructions seed). `DETAIL_FIELDS`
are the prose the listing omits, fetched on demand by `node_detail`. The
two sets partition every Abstract field, so "detail" is exactly "what the
summary didn't give you". Keeping the split here, as field lists over the
raw dict, means no schema change and one place to retune the boundary.
"""

from typing import Any

# Cheap, always-listed fields. Mirrors the AbstractCore fields that are
# short (title, topical/entity labels) plus the two tag facets — never the
# long prose, which lives in DETAIL_FIELDS.
SUMMARY_FIELDS: tuple[str, ...] = (
    "title",
    "topics",
    "domains",
    "intended_audience",
    "persons",
    "organizations",
    "works",
    "other_entities",
    "locations",
    "time_period",
    "language",
    "content_tags",
    "format_tags",
)

# The prose the agent asks for explicitly via `node_detail`. `running_summary`
# only exists on blob abstracts; projecting it off a node abstract is a no-op.
DETAIL_FIELDS: tuple[str, ...] = (
    "summary",
    "key_questions",
    "key_claims",
    "running_summary",
)


def project(abstract: dict[str, Any] | None, fields: tuple[str, ...]) -> dict[str, Any]:
    """Pick `fields` (those present) off the stored Abstract dict. A missing
    abstract (None — only possible on the defensive node path) projects to {}.
    """
    if abstract is None:
        return {}
    return {key: abstract[key] for key in fields if key in abstract}


def summary_abstract(abstract: dict[str, Any] | None) -> dict[str, Any]:
    return project(abstract, SUMMARY_FIELDS)


def detail_abstract(abstract: dict[str, Any] | None) -> dict[str, Any]:
    return project(abstract, DETAIL_FIELDS)


def abstract_title(abstract: dict[str, Any] | None) -> str | None:
    if abstract is None:
        return None
    title = abstract.get("title")
    return title if isinstance(title, str) else None


def abstract_tags(abstract: dict[str, Any] | None) -> list[str]:
    """The user-facing flat tag list: content facets then format facets."""
    if abstract is None:
        return []
    content = abstract.get("content_tags") or []
    fmt = abstract.get("format_tags") or []
    return [*content, *fmt]
