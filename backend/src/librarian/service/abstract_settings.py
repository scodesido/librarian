from pydantic import BaseModel


class AbstractSettings(BaseModel):
    """Per-field budgets for the Abstract LLM agents. Embedded as a
    section under each worker's settings (`BlobExtractorSettings`,
    `NodeExtractorSettings`) so blob and node can be tuned independently
    — e.g. node summaries can grow longer near the root without
    affecting the blob path.

    Field *meanings* live as `Field(description=...)` on `Abstract`
    itself (see service/abstract.py) and travel to the LLM via the JSON
    schema. The numeric budgets live here and reach the LLM via the
    agent's instructions: each worker's agent builder interpolates
    `budgets_text` (or `rolling_budgets_text` for the blob agent, which
    targets `RollingAbstract`) into its instructions string. That keeps
    "what each field means" in the schema, "how big each field should
    be" in the instructions, and "how that budget is rendered" in one
    place — this class — so there's no drift between workers.
    """

    title_words: int = 8
    summary_words: int = 100
    topics_count: int = 5
    key_questions_count: int = 3
    key_claims_count: int = 3
    # Single cap applied to each entity bucket (persons, organizations,
    # works, other_entities) individually.
    entities_max_count: int = 5
    locations_max_count: int = 5
    time_period_max_count: int = 3
    language_max_count: int = 3
    # Only consumed by the RollingAbstract (blob) path via
    # `rolling_budgets_text`. `budgets_text` (node path) omits it.
    running_summary_words: int = 80

    @property
    def budgets_text(self) -> str:
        """Bullet-list snippet for the agent instructions covering the
        base `Abstract` fields. Caller adds its own header (e.g.
        "Field budgets:\\n") and trailing whitespace.
        """
        return (
            f"- title: roughly {self.title_words} words\n"
            f"- summary: roughly {self.summary_words} words\n"
            f"- topics: about {self.topics_count} items\n"
            f"- key_questions: up to {self.key_questions_count} items\n"
            f"- key_claims: up to {self.key_claims_count} items\n"
            f"- persons, organizations, works, other_entities: up to "
            f"{self.entities_max_count} items each\n"
            f"- locations: up to {self.locations_max_count} items\n"
            f"- time_period: up to {self.time_period_max_count} items\n"
            f"- language: up to {self.language_max_count} items"
        )

    @property
    def rolling_budgets_text(self) -> str:
        """`budgets_text` plus the running_summary line. Used by the
        blob agent, whose output type is `RollingAbstract`.
        """
        return (
            f"{self.budgets_text}\n"
            f"- running_summary: roughly {self.running_summary_words} words"
        )
