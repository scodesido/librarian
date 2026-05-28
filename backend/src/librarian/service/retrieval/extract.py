from pydantic import BaseModel, Field
from pydantic_ai import Agent

from librarian.api.settings import QuerySettings
from librarian.service.llm import build_llm_model


class ExtractedTerms(BaseModel):
    """Output of the search-terms extraction agent. `terms` is what we
    embed for similarity scoring; `rationale` is a short note useful in
    logs and (optionally) in the UI to explain why the extracted string
    diverges from the original question.
    """

    terms: str = Field(
        description=(
            "A short search-terms string capturing the key topics, entities, "
            "and concepts in the user's question. Plain text, no quotes, no "
            "formatting, no leading 'Search:' or similar. Conversational "
            "framing (first-person phrasing, polite filler, references to "
            "what the user remembers or is looking for) should be dropped; "
            "names, technical terms, and domain words should be kept verbatim."
        ),
        min_length=1,
    )
    rationale: str = Field(
        description=(
            "One sentence on what was kept vs dropped, for logging and UI "
            "display. Keep it under ~20 words."
        )
    )


EXTRACT_INSTRUCTIONS = (
    "You convert a user's free-form question into a compact search-terms "
    "string suitable for embedding-based similarity search over a personal "
    "document library.\n\n"
    "Goals:\n"
    "  * Keep the topical content: domain words, technical terms, named "
    "entities (people, organisations, works, places), time references.\n"
    "  * Drop conversational framing: first-person verbs ('I'm looking for', "
    "'I remember', 'can you find'), politeness, hedges, references to where "
    "the user saw the material.\n"
    "  * Prefer noun phrases over full sentences. Order does not matter much; "
    "what matters is the bag of meaningful words.\n"
    "  * Don't paraphrase aggressively — keep the user's vocabulary so the "
    "vectors stay close to how the documents themselves are likely worded.\n"
    "  * Don't add new content the user didn't mention.\n\n"
    "Output is a structured ExtractedTerms with `terms` (the string to embed) "
    "and a short `rationale` explaining what you kept/dropped. If the "
    "question is already terse and well-framed, `terms` may be nearly "
    "identical to the question — that's fine."
)


def build_extractor_agent(settings: QuerySettings) -> Agent[None, ExtractedTerms]:
    """Per-request pydantic-ai Agent for the pre-flight extraction step.
    No tools, no deps — it's a one-shot input -> structured output call.
    Same provider plumbing as the retrieval agent so a single set of LLM
    credentials covers both.
    """
    api_token = (
        settings.llm_api_token.get_secret_value()
        if settings.llm_api_token is not None
        else None
    )
    model, model_settings = build_llm_model(
        settings.extract_llm_model,
        api_token=api_token,
        ollama_host=settings.ollama_host,
        ollama_num_ctx=settings.ollama_num_ctx,
        cache_instructions=True,
    )
    agent: Agent[None, ExtractedTerms] = Agent(
        model,
        output_type=ExtractedTerms,
        instructions=EXTRACT_INSTRUCTIONS,
        model_settings=model_settings,
        retries=settings.extract_llm_output_retries,
    )
    return agent


async def extract_search_terms(
    agent: Agent[None, ExtractedTerms], question: str
) -> ExtractedTerms:
    """One-shot call. Returns the structured output verbatim; the caller
    decides what to do with `rationale` (logs, FE, or discard).
    """
    result = await agent.run(question)
    return result.output
