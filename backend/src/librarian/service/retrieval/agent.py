import json
import math
from typing import Any

from asyncpg.pool import PoolConnectionProxy
from pydantic import BaseModel, Field
from pydantic_ai import Agent

from librarian.api.settings import QuerySettings
from librarian.db.tree_children import (
    NodeRow,
    fetch_children,
    fetch_node_abstract,
)
from librarian.service.llm import build_llm_model
from librarian.service.retrieval.deps import QueryDeps
from librarian.service.retrieval.tools import (
    expand_nodes_impl,
    fetch_blob_contents_impl,
)


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
            "starting with 'b:' (taken verbatim from a BlobChildView entry's "
            "`ref` field). Up to the cap given in the instructions. Return "
            "fewer if fewer are relevant. Do not invent or modify refs."
        )
    )
    rationale: str = Field(
        description=("One or two sentences explaining why these blobs were chosen.")
    )


def compute_budget(root_height: int, multiplier: float) -> int:
    """Descent budget = max(2, ceil(C * (root.height + 1))).

    The +1 handles the trivial height-0 case (the whole library fits as
    blob children of a single root) — without it the budget would be 0 and
    the agent couldn't make a single expand_nodes call. The floor of 2
    guarantees the agent always has at least one descent and one revisit,
    even at C close to zero.
    """
    return max(2, math.ceil(multiplier * (root_height + 1)))


async def build_seed_context(
    conn: PoolConnectionProxy, user_id: int, root: NodeRow
) -> dict[str, Any]:
    """Materialise the seed the agent sees in its instructions: the root's
    own abstract plus the abstracts of the root's immediate children. Same
    shape the tool would return on the first expand_nodes call, but inlined
    into the instructions so the agent doesn't have to spend a step on it
    (and so Anthropic prompt caching covers the seed).
    """
    abstract = await fetch_node_abstract(conn, user_id, root.node_id)
    children = await fetch_children(conn, user_id, root)
    return {
        "root_node_id": root.node_id,
        "root_height": root.height,
        "root_abstract": abstract,
        "root_children": [c.model_dump() for c in children],
    }


def build_instructions(
    settings: QuerySettings, budget: int, seed: dict[str, Any]
) -> str:
    seed_json = json.dumps(seed, indent=2, ensure_ascii=False)
    return (
        "You are a retrieval agent that walks a user's document library, "
        "organised as an abstraction tree, to answer the user's question by "
        "selecting the most relevant document blobs.\n\n"
        "Tree shape: every node has an Abstract (summary, topics, key claims, "
        "etc.). Internal nodes' Abstracts synthesize their children's. Leaf "
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
        "Tools you may call:\n"
        f"  * expand_nodes(node_refs): pass up to "
        f"{settings.tool_node_id_max_count} node refs (each starts with 'n:'); "
        "receive each node's immediate children. Use this to descend toward "
        "relevant subtrees. You may select refs from different subtrees in a "
        "single call.\n"
        f"  * fetch_blob_contents(blob_refs): inspect plaintext of one or "
        f"more blobs (up to {settings.max_returned_blobs} refs per call; each "
        "starts with 'b:'). Use this when you're at the blob level and want "
        "to confirm relevance before finalising. Does not count against the "
        f"descent budget but is capped at {settings.max_blob_content_fetches} "
        "total calls per query.\n\n"
        f"Descent budget: you have {budget} expand_nodes calls for this query. "
        "Budget exhaustion raises an error — emit your best answer before then.\n\n"
        "You may BACKTRACK at any point: re-expand a node from earlier in your "
        "exploration if you decide a different branch looks more promising. "
        "The budget allows for several reconsiderations on top of straight "
        "descent — use them.\n\n"
        f"Final answer: emit a FinalAnswer with up to {settings.max_returned_blobs} "
        "blob_refs (each starts with 'b:') in priority order, plus a short "
        "rationale. Return fewer if fewer are clearly relevant; do not pad.\n\n"
        "Library seed (root abstract + root's immediate children Abstracts):\n"
        f"{seed_json}"
    )


def build_query_agent(
    settings: QuerySettings, instructions: str
) -> Agent[QueryDeps, FinalAnswer]:
    """Build the per-request pydantic-ai Agent. Caching of the instructions
    block is requested via `cache_instructions=True`; the LLM builder turns
    that into provider-specific settings (Anthropic: yes, Ollama: ignored).
    """
    anthropic_api_key = (
        settings.anthropic_api_key.get_secret_value()
        if settings.anthropic_api_key is not None
        else None
    )
    model, model_settings = build_llm_model(
        settings.llm_model,
        anthropic_api_key=anthropic_api_key,
        ollama_host=settings.ollama_host,
        ollama_num_ctx=settings.ollama_num_ctx,
        cache_instructions=True,
    )
    agent: Agent[QueryDeps, FinalAnswer] = Agent(
        model,
        output_type=FinalAnswer,
        deps_type=QueryDeps,
        instructions=instructions,
        model_settings=model_settings,
        retries=settings.llm_output_retries,
        tools=[expand_nodes_impl, fetch_blob_contents_impl],
    )
    return agent
