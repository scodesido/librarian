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
    # librarian/service/llm.py. "anthropic:...", "openai:...",
    # "xai:..." or "ollama:..." supported.
    #
    # Split by node height: height-0 (leaf) nodes synthesize from blob
    # Abstracts, a relatively constrained task that a small/cheap model
    # handles well. Height>0 (internal) nodes synthesize from synthesized
    # Abstracts — each subsequent level adds compression and the model
    # has to keep more nuance in mind to write a summary that lets the
    # retrieval agent reach every child (including outliers). A more
    # capable model is worth the cost there. Defaults reflect that:
    # haiku for leaves, sonnet for internal. Both can be overridden
    # independently in YAML, e.g. set both to the same model to disable
    # the split, or point leaf at a local ollama and internal at
    # anthropic to mix providers.
    llm_model_leaf: str = "anthropic:claude-haiku-4-5"
    llm_model_internal: str = "anthropic:claude-sonnet-4-5"
    # Single LLM api token used for whichever provider both
    # `llm_model_leaf` and `llm_model_internal` resolve to. Sharing one
    # token is the common case (same provider across heights, possibly
    # different model sizes); if a user wires the two heights to
    # different providers, the same token field carries that provider's
    # key — the chosen model string determines which provider consumes
    # it. Unused for ollama, which has no auth.
    llm_api_token: SecretStr | None = None

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
