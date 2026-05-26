from pydantic import BaseModel, Field, field_validator, model_validator

from librarian.service.tags import ContentTag, FormatTag


class AbstractCore(BaseModel):
    """Synthesized fields produced by the main LLM agent (blob path) or
    the node-rollup agent (node path). Does NOT include the facet tags
    — those come from a dedicated classifier on the blob path and from
    the deterministic set-union of children's tags on the node path.

    Field *meanings* live as `Field(description=...)` on each field and
    travel to the LLM as JSON-schema property descriptions. Numeric
    *budgets* (word counts, item caps) live in `AbstractSettings` and
    reach the LLM through the agent's instructions, interpolated via
    `budgets_text` / `rolling_budgets_text`. That split keeps meanings
    static and budgets per-worker-tunable, without dynamic class
    creation.
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
    domains: list[str] = Field(
        description=(
            "Subject domains the content sits in (e.g. 'machine learning', "
            "'constitutional law', 'civil engineering'). Prefer a single "
            "value for a leaf-level blob."
        ),
    )


class Abstract(AbstractCore):
    """AbstractCore + the two closed-vocabulary facet tags. This is the
    shape persisted in `data_blobs.abstract` and
    `data_node_abstracts.abstract`. The model_validator enforces ≥1 per
    facet unconditionally — every persisted Abstract must satisfy it.

    On the blob path, the tags come from the dedicated tag-classifier
    agent (see service/blob_extractor/tagging.py). On the node path,
    they come from the sorted set-union of the children's tags.
    """

    content_tags: list[ContentTag] = Field(
        default_factory=list,
        description=(
            "Subject-matter facet tags from a fixed closed vocabulary "
            "(e.g. 'math', 'history', 'computer-science'). At least one "
            "is required at every persistence boundary; strongly prefer "
            "exactly one. See librarian.service.tags."
        ),
    )
    format_tags: list[FormatTag] = Field(
        default_factory=list,
        description=(
            "Genre/form facet tags from a fixed closed vocabulary "
            "(e.g. 'article', 'book', 'report'). At least one is "
            "required at every persistence boundary; strongly prefer "
            "exactly one. See librarian.service.tags."
        ),
    )

    # Pydantic's Literal validation already enforces membership; these
    # validators only canonicalise (sort + dedupe) so JSONB on disk is
    # stable and the node-level set-union semantics are deterministic.
    @field_validator("content_tags")
    @classmethod
    def sort_content_tags(cls, v: list[ContentTag]) -> list[ContentTag]:
        return sorted(set(v))

    @field_validator("format_tags")
    @classmethod
    def sort_format_tags(cls, v: list[FormatTag]) -> list[FormatTag]:
        return sorted(set(v))

    @model_validator(mode="after")
    def require_tags_per_facet(self) -> "Abstract":
        if not self.content_tags:
            raise ValueError(
                "content_tags must contain at least one tag; tags are not "
                "optional at persistence — they are what the node-level "
                "union propagates upward"
            )
        if not self.format_tags:
            raise ValueError(
                "format_tags must contain at least one tag; tags are not "
                "optional at persistence — they are what the node-level "
                "union propagates upward"
            )
        return self


class RollingAbstractCore(AbstractCore):
    """Main blob agent's output type: AbstractCore + the rolling summary
    that the LLM weaves blob-to-blob. Tags are NOT in this schema — the
    tag agent produces them separately and the caller assembles the
    final RollingAbstract.
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


class RollingAbstract(Abstract):
    """Final blob-level Abstract persisted to `data_blobs.abstract`:
    Abstract + running_summary. The schema-level `enum` + `minItems: 1`
    constraints for the tag agent's output live on `BlobTags`, not
    here — RollingAbstract is never an LLM output type, it's
    constructed from a validated `RollingAbstractCore` + a validated
    `BlobTags` by `process_file`. Re-validation through the inherited
    `Abstract` validators still catches drift.

    The default empty string on running_summary lets a base Abstract
    JSON validate as a RollingAbstract — useful when a consumer wants
    one uniform shape regardless of whether the row came from
    data_blobs or data_node_abstracts.
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


class BlobTags(BaseModel):
    """Tag-classifier agent's output type. Standalone (not a subclass of
    Abstract) so the LLM's JSON schema contains only the two fields it
    needs to populate, with `enum` (via Literal) and `minItems: 1` (via
    min_length) constraints carried into the schema. That combination
    makes empty or out-of-vocab tag emission structurally impossible
    rather than relying on prompt phrasing.
    """

    content_tags: list[ContentTag] = Field(
        min_length=1,
        description=(
            "Subject-matter facet tags from the allowed vocabulary. AT "
            "LEAST ONE is required; strongly prefer exactly one — add a "
            "second only when the content genuinely spans multiple "
            "domains."
        ),
    )
    format_tags: list[FormatTag] = Field(
        min_length=1,
        description=(
            "Genre/form facet tags from the allowed vocabulary. AT LEAST "
            "ONE is required; strongly prefer exactly one — add a second "
            "only when the content genuinely spans multiple formats."
        ),
    )
