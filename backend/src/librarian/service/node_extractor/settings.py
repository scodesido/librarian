from pydantic import BaseModel, SecretStr

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

    # Model selection. Provider prefix picks the backend; see
    # librarian/service/llm.py. "anthropic:..." or "ollama:..." supported.
    # llm_model: str = "anthropic:claude-haiku-4-5"
    llm_model: str = "ollama:qwen3.5:9b"
    anthropic_api_key: SecretStr | None = None

    # Local ollama daemon URL. Default works for non-containerised dev;
    # in docker-compose the dev config overrides to host.docker.internal.
    ollama_host: str = "http://localhost:11434"

    # Context window requested from ollama (see BlobExtractorSettings for
    # the full rationale). 16384 covers a JSON list of children
    # abstracts comfortably for typical fan-out; bump for very-wide nodes.
    ollama_num_ctx: int = 16384

    # Number of pydantic-ai retries on Abstract validation failure (see
    # BlobExtractorSettings.llm_output_retries for the rationale).
    llm_output_retries: int = 3

    @property
    def get_anthropic_api_key(self) -> str:
        if self.anthropic_api_key is None:
            raise ValueError("node_extractor.anthropic_api_key is not configured")
        return self.anthropic_api_key.get_secret_value()
