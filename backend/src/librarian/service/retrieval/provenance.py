"""Ref provenance: the agent may only pass refs it has actually been shown.

Refs are minted as `<kind>:<id>` and the id spaces are disjoint at the DB
level (a single `data_tree_element_id_seq` feeds both node_id and blob_id), so
a node id can never double as a valid blob id. That kills the *cross-kind*
collision the agent hit — reusing a node it just inspected as a `b:` ref. It
does not, on its own, stop the agent from naming a real *same-kind* element it
never reached, or hallucinating a ref outright.

This module is the second layer: every tool calls `ensure_refs_seen` on its
inputs before touching the DB, and `record_seen_refs` on whatever it surfaces.
The seen-set is seeded with the instructions seed's refs (see
`run.setup_query`). A ref the agent didn't reach through descent is refused
with a `ModelRetry` that points it back at `list_children`. See
docs/20.retrieval_ref_integrity.md.
"""

from typing import Iterable

from pydantic_ai import ModelRetry

from librarian.service.retrieval.deps import QueryDeps


def ensure_refs_seen(deps: QueryDeps, refs: Iterable[str]) -> None:
    """Raise `ModelRetry` if any of `refs` was never surfaced to the agent.
    Called at the top of every tool, after the cheap format parse, so a
    fabricated ref becomes a corrective retry rather than a silent lookup of
    the wrong element.
    """
    unseen = [ref for ref in refs if ref not in deps.seen_refs]
    if unseen:
        raise ModelRetry(
            f"these refs were never shown to you: {unseen}. You may only pass "
            "refs that appeared in the seed or in a previous tool result. "
            "Reach new nodes and blobs by descending with list_children — "
            "never construct a ref from an id you saw elsewhere."
        )


def record_seen_refs(deps: QueryDeps, refs: Iterable[str]) -> None:
    """Register refs the agent has now legitimately seen (the children a
    list_children returned, the file blobs a list_file_blobs listed), making
    them valid inputs to subsequent tool calls.
    """
    deps.seen_refs.update(refs)
