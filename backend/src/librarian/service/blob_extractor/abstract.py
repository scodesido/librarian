from pydantic_ai import Agent, BinaryContent

from librarian.service.abstract import RollingAbstract
from librarian.service.blob_extractor.settings import BlobExtractorSettings
from librarian.service.llm import build_llm_model


def build_abstract_agent(
    settings: BlobExtractorSettings,
) -> Agent[None, RollingAbstract]:
    instructions = (
        "You analyze a single blob of content extracted from a larger document "
        "and produce a structured Abstract describing it.\n\n"
        "Field constraints:\n"
        f"- summary: roughly {settings.summary_words} words; concise and "
        "informative.\n"
        f"- topics: about {settings.topics_count} short topic strings, "
        "each 1-4 words.\n"
        "- intended_audience: a short phrase describing who would read this "
        "content.\n"
        "- content_type: 1-3 tags from {essay, data, technical doc, law, "
        "charts, narrative, reference, code, other}.\n"
        "- domains: ideally one domain (e.g. 'machine learning', "
        "'constitutional law', 'civil engineering'). For a single blob, "
        "prefer a single value.\n"
        f"- running_summary: roughly {settings.running_summary_words} words. "
        "If a previous running summary is provided, weave the new blob into "
        "it; otherwise infer what the whole document seems to be about from "
        "this first blob alone."
    )
    model = build_llm_model(settings.llm_model, settings.get_anthropic_api_key)
    return Agent(model, output_type=RollingAbstract, instructions=instructions)


async def extract_abstract(
    agent: Agent[None, RollingAbstract],
    content: bytes | str,
    media_type: str,
    previous_running_summary: str | None,
) -> RollingAbstract:
    parts: list[str | BinaryContent] = []
    if previous_running_summary is None:
        parts.append(
            "This is the first blob of the file; there is no previous running "
            "summary. Use the running_summary field to convey what the whole "
            "document seems to be about based on this first blob alone."
        )
    else:
        parts.append(f"Previous running summary:\n{previous_running_summary}")
    if isinstance(content, bytes):
        parts.append(BinaryContent(data=content, media_type=media_type))
    else:
        parts.append(f"Blob content:\n\n{content}")
    result = await agent.run(parts)
    return result.output
