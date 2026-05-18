import json
from typing import Any

from pydantic_ai import Agent

from librarian.service.abstract import Abstract
from librarian.service.llm import build_llm_model
from librarian.service.node_extractor.settings import NodeExtractorSettings


def build_node_abstract_agent(
    settings: NodeExtractorSettings,
) -> Agent[None, Abstract]:
    instructions = (
        "You are given a JSON list of children Abstracts. The children come "
        "from a clustered subtree of a user's document library; your job is "
        "to synthesize a single Abstract that captures the shared themes, "
        "content types, audience and domains of the group as a whole.\n\n"
        "Field constraints:\n"
        f"- summary: roughly {settings.summary_words} words; a clear synthesis "
        "of what the whole group is collectively about (not a list of the "
        "children's summaries).\n"
        f"- topics: about {settings.topics_count} short topic strings, each "
        "1-4 words. Prefer topics that appear across multiple children; "
        "consolidate near-duplicates rather than enumerating every child's "
        "topics verbatim.\n"
        "- intended_audience: the audience that would care about this group "
        "as a whole.\n"
        "- content_type: 1-3 tags from {essay, data, technical doc, law, "
        "charts, narrative, reference, code, other} that best describe the "
        "group.\n"
        "- domains: one to three domains the group sits in."
    )
    model = build_llm_model(settings.llm_model, settings.get_anthropic_api_key)
    return Agent(model, output_type=Abstract, instructions=instructions)


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
