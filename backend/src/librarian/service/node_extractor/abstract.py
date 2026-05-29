import json
from dataclasses import dataclass
from typing import Any

from pydantic_ai import Agent

from librarian.service.abstract import Abstract, AbstractCore
from librarian.service.credentials import ModelCreds
from librarian.service.llm import build_llm_model
from librarian.service.node_extractor.settings import NodeExtractorSettings
from librarian.service.usage import TokenUsage, agent_usage


@dataclass(frozen=True)
class NodeAgents:
    """Per-height agent pair. `leaf` runs on height-0 nodes (children
    are blob Abstracts), `internal` runs on height>0 nodes (children
    are node Abstracts, themselves already a synthesis — a more
    capable model pays off here). Built once per worker iteration and
    threaded through `process_one_node`, which picks which to use
    based on the claimed node's height.

    Plain dataclass (not Pydantic BaseModel): the fields are
    pydantic-ai `Agent` instances, which aren't a pydantic-validatable
    type. We never serialise or round-trip this container — it's just
    a lightweight bag — so the pydantic machinery would only get in
    the way (and indeed pydantic's CoreSchema generation fails on
    `Agent` even with `arbitrary_types_allowed=True`).
    """

    leaf: Agent[None, AbstractCore]
    internal: Agent[None, AbstractCore]

    def for_height(self, height: int) -> Agent[None, AbstractCore]:
        return self.leaf if height == 0 else self.internal


def build_node_abstract_agent(
    settings: NodeExtractorSettings,
    creds: ModelCreds,
) -> Agent[None, AbstractCore]:
    # Field *meanings* travel via the output schema (Field(description=...)
    # on AbstractCore). The instructions add what the schema can't:
    # synthesis task context, per-field budgets rendered by
    # AbstractSettings, and the rule that entity/location fields must
    # only carry forward items that appear in the children's Abstracts.
    # The LLM produces AbstractCore (no tag fields at all in the
    # schema); tags are computed deterministically by the caller as the
    # sorted set-union of children's tags. `budgets_text` (not
    # `rolling_budgets_text`) — node targets the base AbstractCore, no
    # running_summary at this layer.
    instructions = (
        "You are given a JSON list of children Abstracts. The children come "
        "from a clustered subtree of a user's document library. Synthesize a "
        "single Abstract that captures what the whole group is collectively "
        "about — merge near-duplicates and consolidate themes, do not "
        "enumerate each child's fields verbatim. Each field's meaning is "
        "given in the output schema; the budgets below are soft targets "
        "for sizing each field.\n\n"
        "Field budgets:\n"
        f"{settings.abstract.budgets_text}\n\n"
        "About the `summary` field: this Abstract will be read by a "
        "downstream retrieval agent that walks the tree top-down to find "
        "the children most relevant to a user's question. The `summary` is "
        "that agent's primary cue for deciding (a) whether to descend into "
        "this subtree at all and (b) which children to follow once it does. "
        "Write it so that every child is reachable through it. Specifically:\n"
        "  - Cover the breadth of what is underneath, not just the dominant "
        "theme. If the children share one broad subject, name it; if they "
        "split into a few distinct subjects, name each.\n"
        "  - Call out outliers by name. If most children cover one topic "
        "and one or two diverge into something different (the 'odd one "
        "out'), the summary MUST mention those outliers explicitly — "
        "otherwise the retrieval agent will never descend to them. A short "
        "phrase is enough (e.g. '… and one chapter on medieval poetry'), "
        "but the outlier subject has to appear in the text.\n"
        "  - Favor concrete, search-friendly vocabulary (the specific "
        "topics, domains, entities the children actually discuss) over "
        "generic framing ('various documents about several topics').\n\n"
        "For persons, organizations, works, other_entities, and locations, "
        "include only items that already appear in the children's Abstracts "
        "(those have already been filtered to explicit mentions). Pick the "
        "most representative across the group; leave the list empty if no "
        "such items appear in the children — do not invent or infer."
    )
    model, model_settings = build_llm_model(
        creds.model,
        api_token=creds.api_token,
        ollama_host=creds.ollama_host,
        ollama_num_ctx=creds.ollama_num_ctx,
    )
    return Agent(
        model,
        output_type=AbstractCore,
        instructions=instructions,
        model_settings=model_settings,
        retries=settings.llm_output_retries,
    )


async def extract_node_abstract(
    agent: Agent[None, AbstractCore],
    children_abstracts: list[dict[str, Any]],
) -> tuple[Abstract, TokenUsage]:
    """Produce a node-level Abstract plus the call's token usage.

    The LLM produces an `AbstractCore` (no tags in the schema, so the
    model never has to reason about them). The caller computes the
    children's tag union and constructs the final `Abstract` via
    `Abstract.model_validate`, which re-runs the unconditional
    ≥1-per-facet validator. If children somehow lack tags (legacy data,
    bug upstream), this raises and the worker's backoff loop surfaces
    it. The closed vocabularies in `service/tags.py` bound the union,
    so a node at any height carries at most |CONTENT_TAGS| +
    |FORMAT_TAGS| tags.
    """
    payload = json.dumps(children_abstracts, indent=2, ensure_ascii=False)
    prompt = (
        "Children Abstracts (as JSON):\n\n"
        f"{payload}\n\n"
        "Produce a single Abstract that synthesizes the whole group."
    )
    result = await agent.run([prompt])
    core = result.output
    content_union: set[str] = set()
    format_union: set[str] = set()
    for child in children_abstracts:
        content_union.update(child.get("content_tags", []))
        format_union.update(child.get("format_tags", []))
    abstract = Abstract.model_validate(
        {
            **core.model_dump(),
            "content_tags": sorted(content_union),
            "format_tags": sorted(format_union),
        }
    )
    return abstract, agent_usage(result)
