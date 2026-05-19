from pydantic import BaseModel, Field


class Abstract(BaseModel):
    """Per-node/per-blob structured summary. The base shape (no
    running_summary) is what node_extractor produces for internal nodes,
    where there's no notion of a rolling chain.

    Field *meanings* live in `Field(description=...)` below. pydantic-ai
    forwards each description to the LLM as a JSON-schema property
    description (via `TypeAdapter.json_schema()`), so the schema is the
    source of truth for what each field is for. Numeric *budgets* (how
    many words, how many items) live separately in `AbstractSettings`
    (see service/abstract_settings.py) and reach the LLM through the
    agent's instructions, interpolated per-worker via that class's
    `budgets_text` / `rolling_budgets_text` helpers. That split keeps
    meanings static and budgets per-worker-tunable, without dynamic
    class creation.
    """

    title: str = Field(
        description="Short display title summarizing what this content is about.",
    )
    summary: str = Field(
        description="Concise prose synthesis of the content's substance.",
    )
    topics: list[str] = Field(
        description=(
            "Short topical labels (each 1-4 words) naming the substantive "
            "themes the content concerns."
        ),
    )
    key_questions: list[str] = Field(
        description=(
            "Natural-language questions this content answers; phrase them "
            "the way a user would ask."
        ),
    )
    key_claims: list[str] = Field(
        description=(
            "Explicit assertions or findings the content makes, as short "
            "declarative sentences."
        ),
    )
    persons: list[str] = Field(
        description=(
            "Persons EXPLICITLY mentioned by name in the content. "
            "Leave this list empty if no persons are explicitly mentioned — "
            "do not invent or infer."
        ),
    )
    organizations: list[str] = Field(
        description=(
            "Organizations (companies, institutions, agencies, ...) "
            "EXPLICITLY mentioned by name in the content. "
            "Leave this list empty if none are explicitly mentioned — "
            "do not invent or infer."
        ),
    )
    works: list[str] = Field(
        description=(
            "Specific works EXPLICITLY referenced by name: books, papers, "
            "laws, technical standards, named products. "
            "Leave this list empty if none are explicitly mentioned — "
            "do not invent or infer."
        ),
    )
    other_entities: list[str] = Field(
        description=(
            "Other named entities EXPLICITLY mentioned that don't fit "
            "persons/organizations/works (events, named projects, ...). "
            "Leave this list empty if none are explicitly mentioned — "
            "do not invent or infer."
        ),
    )
    locations: list[str] = Field(
        description=(
            "Geographical locations EXPLICITLY mentioned in the content "
            "(cities, regions, countries, named landmarks). "
            "Leave this list empty if none are explicitly mentioned — "
            "do not invent or infer."
        ),
    )
    time_period: list[str] = Field(
        description=(
            "Time periods the content concerns (e.g. '1920s', 'Q3 2024', "
            "'Late Antiquity'). What the content is about temporally, not "
            "when the document itself was authored."
        ),
    )
    language: list[str] = Field(
        description=(
            "Natural languages used in the content (e.g. 'English', 'French')."
        ),
    )
    intended_audience: str = Field(
        description="Short phrase describing who would read this content.",
    )
    content_type: list[str] = Field(
        description=(
            "Format/style tags. 1-3 items chosen from: essay, data, "
            "technical doc, law, charts, narrative, reference, code, other."
        ),
    )
    domains: list[str] = Field(
        description=(
            "Subject domains the content sits in (e.g. 'machine learning', "
            "'constitutional law', 'civil engineering'). Prefer a single "
            "value for a leaf-level blob."
        ),
    )


class RollingAbstract(Abstract):
    """blob_extractor's per-blob Abstract: the base fields plus a
    running_summary that the LLM weaves into the previous blob's
    running_summary, anchoring the chain across one file's blobs.

    The default empty string lets a base Abstract JSON validate as a
    RollingAbstract — useful when a consumer wants one uniform shape
    regardless of whether the row came from data_blobs or
    data_node_abstracts.
    """

    running_summary: str = Field(
        default="",
        description=(
            "Rolling summary of the document so far. For the first blob of "
            "a file infer what the whole document seems to be about from "
            "this first blob alone; for subsequent blobs weave the new "
            "blob's content into the previous running_summary supplied in "
            "the user prompt."
        ),
    )
