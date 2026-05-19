from pydantic_ai import Agent, BinaryContent

from librarian.service.abstract import RollingAbstract
from librarian.service.blob_extractor.settings import BlobExtractorSettings
from librarian.service.llm import build_llm_model


def build_abstract_agent(
    settings: BlobExtractorSettings,
) -> Agent[None, RollingAbstract]:
    # Field *meanings* travel via the output schema (Field(description=...)
    # on RollingAbstract). The instructions add what the schema can't:
    # task context, per-field budgets rendered by AbstractSettings, and
    # the explicit-mention rule. `rolling_budgets_text` includes the
    # running_summary line because the blob agent targets RollingAbstract.
    instructions = (
        "You analyze a single blob of content extracted from a larger "
        "document and produce a structured Abstract describing it. Each "
        "field's meaning is given in the output schema; the budgets below "
        "are soft targets for sizing each field.\n\n"
        "Field budgets:\n"
        f"{settings.abstract.rolling_budgets_text}\n\n"
        "For persons, organizations, works, other_entities, and locations, "
        "include only items that are EXPLICITLY mentioned in this blob's "
        "content. Leave the list empty if no such items are explicitly "
        "mentioned — do not invent or infer."
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
