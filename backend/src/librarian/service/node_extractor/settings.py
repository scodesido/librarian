from pydantic import BaseModel, SecretStr


class NodeExtractorSettings(BaseModel):
    # Worker loop
    poll_interval_seconds: float = 5.0
    concurrent_workers: int = 1

    # Error handling: per-worker exponential backoff.
    error_backoff_initial_seconds: float = 5.0
    error_backoff_max_seconds: float = 300.0
    error_backoff_multiplier: float = 2.0

    # Abstract shape (soft constraints passed to the LLM prompt).
    summary_words: int = 100
    topics_count: int = 5

    # Model selection.
    llm_model: str = "anthropic:claude-haiku-4-5"
    anthropic_api_key: SecretStr | None = None

    @property
    def get_anthropic_api_key(self) -> str:
        if self.anthropic_api_key is None:
            raise ValueError("node_extractor.anthropic_api_key is not configured")
        return self.anthropic_api_key.get_secret_value()
