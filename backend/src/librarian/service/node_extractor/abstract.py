import json
from typing import Any

from pydantic_ai import Agent

from librarian.service.abstract import Abstract
from librarian.service.llm import build_llm_model
from librarian.service.node_extractor.settings import NodeExtractorSettings


def build_node_abstract_agent(
    settings: NodeExtractorSettings,
) -> Agent[None, Abstract]:
    # Field *meanings* travel via the output schema (Field(description=...)
    # on Abstract). The instructions add what the schema can't: synthesis
    # task context, per-field budgets rendered by AbstractSettings, and
    # the rule that entity/location fields must only carry forward items
    # that appear in the children's Abstracts. `budgets_text` (not
    # `rolling_budgets_text`) — node targets the base Abstract, no
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
        "For persons, organizations, works, other_entities, and locations, "
        "include only items that already appear in the children's Abstracts "
        "(those have already been filtered to explicit mentions). Pick the "
        "most representative across the group; leave the list empty if no "
        "such items appear in the children — do not invent or infer."
    )
    api_key = (
        settings.anthropic_api_key.get_secret_value()
        if settings.anthropic_api_key is not None
        else None
    )
    model, model_settings = build_llm_model(
        settings.llm_model,
        anthropic_api_key=api_key,
        ollama_host=settings.ollama_host,
        ollama_num_ctx=settings.ollama_num_ctx,
    )
    return Agent(
        model,
        output_type=Abstract,
        instructions=instructions,
        model_settings=model_settings,
        retries=settings.llm_output_retries,
    )


async def extract_node_abstract(
    agent: Agent[None, Abstract],
    children_abstracts: list[dict[str, Any]],
) -> Abstract:
    payload = json.dumps(children_abstracts, indent=2, ensure_ascii=False)
    prompt = (
        "Children Abstracts (as JSON):\n\n"
        f"{payload}\n\n"
        "Produce a single Abstract that synthesizes the whole group."
    )
    result = await agent.run([prompt])
    return result.output
