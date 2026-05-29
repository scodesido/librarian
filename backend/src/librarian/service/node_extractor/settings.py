from pydantic import BaseModel

from librarian.service.abstract_settings import AbstractSettings


class NodeExtractorSettings(BaseModel):
    # Worker loop
    poll_interval_seconds: float = 5.0
    concurrent_workers: int = 1

    # Error handling: per-worker exponential backoff.
    error_backoff_initial_seconds: float = 5.0
    error_backoff_max_seconds: float = 300.0
    error_backoff_multiplier: float = 2.0

    # Per-field budgets for the LLM-produced Abstract. Field meanings
    # live as Field(description=...) on service/abstract.py and reach
    # the LLM via the JSON schema; AbstractSettings owns the numeric
    # budgets and renders them into the agent's instructions via
    # `budgets_text` (node targets the base Abstract — running_summary
    # doesn't apply). Independent from blob_extractor's instance so
    # node summaries can be tuned separately (e.g. longer near the root).
    abstract: AbstractSettings = AbstractSettings()

    # Number of pydantic-ai retries on Abstract validation failure (see
    # BlobExtractorSettings.llm_output_retries for the rationale).
    llm_output_retries: int = 3
