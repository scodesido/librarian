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
    # Pass both provider knobs unconditionally; build_llm_model picks the
    # one its provider branch needs and raises if it's missing. This lets
    # the user flip llm_model between "anthropic:..." and "ollama:..." in
    # settings without code changes.
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
        output_type=RollingAbstract,
        instructions=instructions,
        model_settings=model_settings,
        retries=settings.llm_output_retries,
    )


async def extract_abstract(
    agent: Agent[None, RollingAbstract],
    content_parts: list[str | BinaryContent],
    previous_running_summary: str | None,
) -> RollingAbstract:
    """Run the agent with a previous-running-summary header and a
    caller-built `content_parts` list. The list can carry any mix of
    strings (text) and BinaryContent (PDF bytes, page images, ...); the
    caller decides what shape matches the configured `llm_pdf_mode`.
    """
    parts: list[str | BinaryContent] = []
    if previous_running_summary is None:
        parts.append(
            "This is the first blob of the file; there is no previous running "
            "summary. Use the running_summary field to convey what the whole "
            "document seems to be about based on this first blob alone."
        )
    else:
        parts.append(f"Previous running summary:\n{previous_running_summary}")
    parts.extend(content_parts)
    result = await agent.run(parts)
    return result.output
