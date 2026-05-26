"""Closed-vocabulary tagging facets for Abstract.

Two facets — `content_tags` (subject matter) and `format_tags`
(genre/form) — are kept deliberately small so that the
`sorted(set(...))` union of children's tags at each internal node stays
bounded by the vocabularies themselves rather than growing with library
size. See docs/12.tags.md for the rationale (Ranganathan PMEST,
LCSH+LCGFT, FAST, BISAC) and the rules for growing the lists.

The vocabularies are defined as `typing.Literal` aliases so the
JSON schema handed to the tag-classification LLM carries the values
as an `enum`. The `frozenset` constants are derived from the Literal
args via `typing.get_args`, keeping a single source of truth.
"""

from typing import Literal, get_args

ContentTag = Literal[
    "art",
    "biology",
    "business",
    "chemistry",
    "computer-science",
    "earth-science",
    "economics",
    "education",
    "engineering",
    "finance",
    "history",
    "law",
    "linguistics",
    "literature",
    "math",
    "medicine",
    "philosophy",
    "physics",
    "politics",
    "psychology",
    "religion",
    "sociology",
    "statistics",
]

FormatTag = Literal[
    "article",
    "book",
    "code",
    "dataset",
    "essay",
    "guide",
    "letter",
    "notes",
    "paper",
    "presentation",
    "reference",
    "report",
    "spec",
]

CONTENT_TAGS: frozenset[str] = frozenset(get_args(ContentTag))
FORMAT_TAGS: frozenset[str] = frozenset(get_args(FormatTag))
