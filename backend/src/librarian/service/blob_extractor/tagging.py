from pydantic_ai import Agent

from librarian.service.abstract import BlobTags, RollingAbstractCore
from librarian.service.blob_extractor.settings import BlobExtractorSettings
from librarian.service.credentials import ModelCreds
from librarian.service.llm import build_llm_model


def build_tag_agent(
    settings: BlobExtractorSettings,
    creds: ModelCreds,
) -> Agent[None, BlobTags]:
    """Dedicated classifier for a blob's `content_tags` / `format_tags`.

    The agent runs after the main blob agent (see `abstract.py`) on the
    main agent's compact output — title, summary, topics, domains —
    rather than the raw blob. That keeps token usage low (~200 input
    tokens per call) and lets the classifier focus on a single task:
    pick the right facet tags from two closed vocabularies.

    The schema-level constraints (Literal types for the vocabularies,
    `min_length=1` on both lists) live on `BlobTags` itself in
    `service/abstract.py`. The LLM literally cannot return `[]` or an
    out-of-vocab string — failures feed `pydantic-ai`'s retry loop,
    but in practice the schema constraints make retries exceptional.

    Shares the blob_llm slot with the main agent — same model, same
    token. A dedicated classifier slot was considered and rejected: the
    tag step is cheap and the two agents benefit from prompt-cache
    sharing on identical instructions when both run against the same
    provider in the same iteration.
    """
    instructions = (
        "You are given a brief description of a document blob — its "
        "title, summary, topics, and domains — and must classify it "
        "into two closed-vocabulary facets:\n"
        "- content_tags: subject-matter facet (math, history, ...)\n"
        "- format_tags:  genre/form facet (article, book, report, ...)\n\n"
        "Budgets:\n"
        f"{settings.abstract.tag_budgets_text}\n\n"
        "Pick the smallest set that correctly classifies the blob. "
        "STRONGLY prefer EXACTLY ONE tag per facet; add a second only "
        "when the content genuinely spans multiple domains or formats. "
        "Both facets REQUIRE at least one tag — the schema enforces "
        "this. The allowed values appear in the output schema as enums."
    )
    model, model_settings = build_llm_model(
        creds.model,
        api_token=creds.api_token,
        ollama_host=creds.ollama_host,
        ollama_num_ctx=creds.ollama_num_ctx,
    )
    return Agent(
        model,
        output_type=BlobTags,
        instructions=instructions,
        model_settings=model_settings,
        retries=settings.llm_output_retries,
    )


async def classify_tags(
    agent: Agent[None, BlobTags],
    core: RollingAbstractCore,
) -> BlobTags:
    """Classify a blob's tags from the main agent's compact output."""
    prompt = (
        f"Title: {core.title}\n\n"
        f"Summary: {core.summary}\n\n"
        f"Topics: {', '.join(core.topics) or '(none)'}\n\n"
        f"Domains: {', '.join(core.domains) or '(none)'}\n\n"
        "Classify into content_tags (subject) and format_tags "
        "(genre/form)."
    )
    result = await agent.run([prompt])
    return result.output
