import json
import math
from typing import Any

import numpy as np
from asyncpg.pool import PoolConnectionProxy
from numpy.typing import NDArray
from pydantic import BaseModel, Field
from pydantic_ai import Agent

from librarian.api.settings import QuerySettings
from librarian.db.tree_children import (
    NodeRow,
    fetch_children_scored,
    fetch_node_abstract,
)
from librarian.service.credentials import ModelCreds
from librarian.service.llm import build_llm_model
from librarian.service.retrieval.deps import QueryDeps
from librarian.service.retrieval.tools.blob_detail import blob_detail_impl
from librarian.service.retrieval.tools.children import list_children_impl
from librarian.service.retrieval.tools.file_blobs import list_file_blobs_impl
from librarian.service.retrieval.tools.node_detail import node_detail_impl
from librarian.service.retrieval.tools.peek import peek_blob_impl
from librarian.service.retrieval.views import child_summary


class FinalAnswer(BaseModel):
    """The agent's structured response. `blob_refs` is the chosen selection
    of blob refs (each starts with 'b:'); capped at
    QuerySettings.max_returned_blobs by the endpoint. `rationale` is a one-
    or two-line note that the FE shows alongside the results — useful for
    debugging the agent's choices.
    """

    blob_refs: list[str] = Field(
        description=(
            "The blob refs you have selected as the best answers to the "
            "user's question, in priority order. Each ref must be a string "
            "starting with 'b:' (taken verbatim from a blob entry's "
            "`ref` field). Up to the cap given in the instructions. Return "
            "fewer if fewer are relevant. Do not invent or modify refs."
        )
    )
    rationale: str = Field(
        description=(
            "One or two sentences, written for the end user, explaining in "
            "plain language why these documents answer their question. The "
            "user has no notion of the library's internals, which are also "
            "subject to change: never mention refs ('b:'/'n:' strings), node "
            "or blob ids, Abstract field names, similarity scores, the tree, "
            "or any other machinery. Speak only about the documents' actual "
            "content and how it relates to what was asked."
        )
    )


def compute_budget(root_height: int, multiplier: float) -> int:
    """Descent budget = max(2, ceil(C * (root.height + 1))).

    The +1 handles the trivial height-0 case (the whole library fits as
    blob children of a single root) — without it the budget would be 0 and
    the agent couldn't make a single list_children call. The floor of 2
    guarantees the agent always has at least one descent and one revisit,
    even at C close to zero.
    """
    return max(2, math.ceil(multiplier * (root_height + 1)))


async def build_seed_context(
    conn: PoolConnectionProxy,
    user_id: int,
    root: NodeRow,
    search_embedding: NDArray[np.float32],
    effective_search_terms: str,
) -> dict[str, Any]:
    """Materialise the seed the agent sees in its instructions: the root's
    own abstract plus the abstracts of the root's immediate children. Same
    shape the tool would return on the first list_children call, but inlined
    into the instructions so the agent doesn't have to spend a step on it
    (and so Anthropic prompt caching covers the seed).

    The root's children are fetched via the scored fetcher so the seed
    already carries `similarity_score` for each — the agent's first
    impression sees the same signal it'll see on every subsequent
    list_children call. `similarity_terms` is also surfaced so the agent
    can reconcile the score field with the actual text that was embedded
    (which may differ from the user's question after the pre-flight
    extraction step). Note that swapping search terms changes the seed
    JSON and therefore invalidates the Anthropic prompt-cache prefix; a
    user re-issuing the same question with the same terms still hits the
    cache.
    """
    abstract = await fetch_node_abstract(conn, user_id, root.node_id)
    children = await fetch_children_scored(conn, user_id, root, search_embedding)
    return {
        "root_node_id": root.node_id,
        "root_height": root.height,
        "root_abstract": abstract,
        "similarity_terms": effective_search_terms,
        # Same summary projection `list_children` returns, so the seed and a
        # first descent step look identical.
        "root_children": [child_summary(c).model_dump() for c in children],
    }


def build_instructions(
    settings: QuerySettings, budget: int, seed: dict[str, Any]
) -> str:
    seed_json = json.dumps(seed, indent=2, ensure_ascii=False)
    return (
        "You are a retrieval agent that walks a user's document library, "
        "organised as an abstraction tree, to answer the user's question by "
        "selecting the most relevant document blobs.\n\n"
        "Tree shape: every node has an Abstract. On a listing you see its "
        "*summary* fields (title, topics, domains, entities, tags). The longer "
        "prose (summary, key questions, key claims) is fetched on demand. "
        "Internal nodes' Abstracts synthesize their children's. Leaf "
        "(height-0) nodes have blob children; each blob carries a portion of "
        "a source document and its own Abstract.\n\n"
        "Refs — IMPORTANT:\n"
        "Every child entry has a `ref` field — an opaque string like "
        "'n:172' (for nodes) or 'b:455' (for blobs). The `node_id` and "
        "`blob_id` integer fields are for human inspection only; the tools "
        "accept refs (the prefixed strings) and refs only. Node and blob id "
        "spaces are independent — the integer 172 can be a valid node id AND "
        "a valid blob id at the same time. The 'n:' / 'b:' prefix is what "
        "tells the tool which one you mean. Always pass `ref` strings "
        "verbatim; never strip the prefix, never construct refs yourself.\n\n"
        "Similarity scores — advisory:\n"
        "Every child entry also carries a `similarity_score` field: cosine "
        "similarity in [-1, 1] between the user's search terms (embedded with "
        "the same model used to index the library) and the child's stored "
        "embedding. This is ADDITIONAL INFORMATION FOR CONSIDERATION, not the "
        "criterion you should optimise. The Abstracts (the summary fields you "
        "see on every listing, plus the prose you can pull with node_detail) "
        "remain the authoritative signal — the score "
        "is a vector-space hint that can complement them, especially when "
        "Abstracts are close in topic but worded differently from the user's "
        "search terms.\n"
        "Two important constraints on how to read it:\n"
        "  1. Compare scores ONLY within siblings of the same parent (i.e. "
        "within one list_children result, among children of the same node). "
        "Absolute thresholds are not meaningful and scores across different "
        "parents are not directly comparable — a 0.45 among one parent's "
        "children may signal a strong match, while a 0.55 among a different "
        "parent's children may be unremarkable.\n"
        "  2. Higher is not automatically better. Treat the score as one "
        "input among many; if the Abstract makes a clearly better case for a "
        "lower-scoring sibling, prefer the Abstract. The score is most useful "
        "as a tiebreaker, as a nudge to investigate a candidate the Abstract "
        "didn't make obvious, or as a reason to revisit a sibling you skipped.\n"
        "The exact text that was embedded to compute these scores is exposed "
        "in the seed below as `similarity_terms` — it may have been derived "
        "from the user's question by a preprocessing step that strips "
        "conversational framing, so it can differ in phrasing while pointing "
        "at the same intent.\n\n"
        "Tools you may call:\n"
        f"  * list_children(node_refs): pass up to "
        f"{settings.tool_node_id_max_count} node refs (each starts with 'n:'); "
        "receive each node's immediate children as summaries (title, tags, "
        "topical/entity labels, similarity score). Use this to descend toward "
        "relevant subtrees. You may select refs from different subtrees in a "
        "single call. This is the only tool that spends descent budget.\n"
        "  * node_detail(node_ref): fetch one node's longer prose (summary, "
        "key questions, key claims) that the listing omits. Use it when a "
        "node's summary looks promising and you want a closer look before "
        "descending. Does not spend descent budget; capped at "
        f"{settings.max_node_detail_fetches} calls.\n"
        "  * blob_detail(blob_ref): the blob counterpart of node_detail — fetch "
        "one blob's prose Abstract fields (summary, key questions, key claims, "
        "running summary) that the summary listings omit. This is the CHEAP way "
        "to inspect a blob; prefer it for triage. Does not spend descent "
        f"budget; capped at {settings.max_blob_detail_fetches} calls.\n"
        f"  * peek_blob(blob_refs): read the full plaintext of one or more blobs "
        f"(up to {settings.max_returned_blobs} refs per call; each starts with "
        "'b:'). This is your most expensive tool — use it SPARINGLY, only to "
        "confirm the handful of candidates you've already narrowed down via "
        "summaries and blob_detail. Do NOT peek blobs by default or peek "
        "everything you encounter; a blob's summary and blob_detail are usually "
        "enough to judge relevance, and you peek only when you need the actual "
        "text to be sure before finalising. Does not spend descent budget; "
        f"capped at {settings.max_blob_content_fetches} total calls.\n"
        "  * list_file_blobs(blob_ref, offset): list the summaries of every "
        "blob in the SAME SOURCE FILE as a blob you've reached, in document "
        "order. Tree position and document position differ — a file's other "
        "fragments may sit in unrelated subtrees. Reach for this once you've "
        "found a blob you like, to see the rest of its document. Paginated: pass the "
        "returned `next_offset` to read more (None means no more). Does not "
        f"spend descent budget; capped at {settings.max_file_blob_listings} "
        "calls.\n\n"
        f"Descent budget: you have {budget} list_children calls for this query. "
        "Budget exhaustion raises an error — emit your best answer before then.\n\n"
        "You may BACKTRACK at any point: re-expand a node from earlier in your "
        "exploration if you decide a different branch looks more promising. "
        "The budget allows for several reconsiderations on top of straight "
        "descent — use them.\n\n"
        f"Final answer: emit a FinalAnswer with up to {settings.max_returned_blobs} "
        "blob_refs (each starts with 'b:') in priority order, plus a short "
        "rationale. Return fewer if fewer are clearly relevant; do not pad.\n"
        "The rationale is shown directly to the end user, who has no notion of "
        "this system's internals — and those internals are subject to change. "
        "So keep it purely semantic: explain in plain language how the chosen "
        "documents' content answers the question. Never expose internals such "
        "as refs ('b:'/'n:' strings), node or blob ids, Abstract field names, "
        "similarity scores, or the tree structure.\n\n"
        "Library seed (root abstract + root's immediate children Abstracts):\n"
        f"{seed_json}"
    )


def build_query_agent(
    settings: QuerySettings,
    creds: ModelCreds,
    instructions: str,
) -> Agent[QueryDeps, FinalAnswer]:
    """Build the per-request pydantic-ai Agent. Caching of the instructions
    block is requested via `cache_instructions=True`; the LLM builder turns
    that into provider-specific settings (Anthropic: yes, Ollama: ignored).
    """
    model, model_settings = build_llm_model(
        creds.model,
        api_token=creds.api_token,
        ollama_host=creds.ollama_host,
        ollama_num_ctx=creds.ollama_num_ctx,
        cache_instructions=True,
    )
    agent: Agent[QueryDeps, FinalAnswer] = Agent(
        model,
        output_type=FinalAnswer,
        deps_type=QueryDeps,
        instructions=instructions,
        model_settings=model_settings,
        retries=settings.llm_output_retries,
        tools=[
            list_children_impl,
            node_detail_impl,
            blob_detail_impl,
            peek_blob_impl,
            list_file_blobs_impl,
        ],
    )
    return agent
