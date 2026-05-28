from typing import Literal

from pydantic import BaseModel, SecretStr

from librarian.service.abstract_settings import AbstractSettings


class BlobExtractorSettings(BaseModel):
    # Worker loop
    poll_interval_seconds: float = 5.0
    concurrent_workers: int = 1

    # Error handling: per-worker exponential backoff.
    error_backoff_initial_seconds: float = 5.0
    error_backoff_max_seconds: float = 300.0
    error_backoff_multiplier: float = 2.0

    # Chunking
    pages_per_blob: int = 10
    words_per_blob: int = 2000

    # Per-field budgets for the LLM-produced Abstract. Field meanings
    # live as Field(description=...) on service/abstract.py and reach
    # the LLM via the JSON schema; AbstractSettings owns the numeric
    # budgets and renders them into the agent's instructions via
    # `rolling_budgets_text` (main blob agent targets RollingAbstractCore).
    # Independent from node_extractor's instance so blob and node can
    # be tuned separately in YAML.
    abstract: AbstractSettings = AbstractSettings()

    # Models. Provider prefix selects the backend:
    #   * LLM: pydantic-ai model string "<provider>:<model>".
    #   * Embedding: librarian.service.embedder dispatch on "<provider>:<model>".
    # Currently wired up:
    #   * llm_model:       "anthropic:...", "openai:...", "xai:...",
    #                      "ollama:..."
    #   * embedding_model: "ollama:...", "voyageai:..."
    # llm_model: str = "anthropic:claude-haiku-4-5"
    llm_model: str = "anthropic:claude-haiku-4-5"
    embedding_model: str = "ollama:qwen3-embedding:0.6b"

    # How PDFs reach the LLM. Three strategies:
    #   * "text":   pypdf-extracted plain text. Works on any model;
    #               loses charts/layout/scans.
    #   * "binary": raw application/pdf bytes. Anthropic native;
    #               local LLMs via ollama OpenAI-compat reject it.
    #   * "images": per-page PNGs rendered with PyMuPDF. Uses the
    #               vision capability of multimodal models (gemma3,
    #               llama3.2-vision, …); ~256 tokens/page.
    # The embedder always sees pypdf-extracted text regardless of mode.
    llm_pdf_mode: Literal["text", "binary", "images"] = "binary"

    # Rasterization DPI for the "images" mode. 150 keeps body text
    # legible after the vision model's internal downscale.
    pdf_image_dpi: int = 150

    # Embedding dimension. Must match the vector(N) column width in the
    # data_blobs schema (currently 1024); changing it requires a migration.
    # Sent to the embedder so Matryoshka-capable models truncate
    # server-side.
    embedding_dimensions: int = 1024

    # Embedder chunking. Long blobs (especially with large pages_per_blob)
    # routinely exceed ollama's default num_ctx of 2048 tokens. We split
    # the embedder input into sub-chunks, embed all in one batched call,
    # then mean + L2-normalise back to one vector per blob.
    #
    # `chunk_chars` is the target size — the chunker aims to break at the
    # first whitespace at or after this many characters. `chunk_chars_max`
    # is the absolute ceiling: if no whitespace exists in
    # [target, max), we hard-cut at max rather than producing an
    # unbounded chunk. ~4 chars/token is the rough heuristic, so 4000 ≈
    # 1000 tokens (safe under default num_ctx); bump both if you raise
    # num_ctx on the ollama side.
    embedding_chunk_chars: int = 4000
    embedding_chunk_chars_max: int = 5000

    # Local ollama daemon URL. The container reaches the host via
    # host.docker.internal (see docker-compose.yaml extra_hosts); a
    # non-containerised dev run leaves the default localhost.
    ollama_host: str = "http://localhost:11434"

    # Context window (in tokens) requested from ollama per call. Ollama's
    # default is 4096, which silently truncates anything longer — bad
    # when our prompt carries a multi-page image blob (~256 tokens/page)
    # plus the running summary and instructions. 16384 fits a typical
    # 5-page blob with headroom; bump higher if you have GPU memory and
    # use a model with a larger native context (qwen2.5: 32k, gemma3:
    # 128k). Passed through pydantic-ai's OpenAI extra_body to ollama's
    # OpenAI-compat handler, which reads it from `options.num_ctx`.
    ollama_num_ctx: int = 16384

    # Number of times pydantic-ai retries the LLM call when its output
    # fails to validate against the Abstract schema. Each retry appends
    # the validation error to the conversation, so the model gets a
    # chance to self-correct. The default of 1 (just one retry) is too
    # tight: a single off-by-one mistake from the model aborts the whole
    # file. 3 has been enough in practice for transient hiccups.
    llm_output_retries: int = 3

    # API tokens passed explicitly to the providers (rather than letting
    # the SDKs read them from env). One token per slot — the chosen
    # model string determines which provider consumes it — rather than
    # one field per provider. This is the seam that will later carry
    # values mounted as secret files, and the shape we expect to expose
    # to end users via the UI (a single "your API key" field per slot,
    # not a key per supported provider).
    #
    # `llm_api_token` covers the LLM model; `embedder_api_token` covers
    # the embedding model. Either is unused for providers that need no
    # auth (ollama). `embedder_api_token` is only required when
    # `embedding_model` selects the voyageai provider.
    llm_api_token: SecretStr | None = None
    embedder_api_token: SecretStr | None = None

    @property
    def get_embedder_api_token(self) -> str:
        if self.embedder_api_token is None:
            raise ValueError("blob_extractor.embedder_api_token is not configured")
        return self.embedder_api_token.get_secret_value()
