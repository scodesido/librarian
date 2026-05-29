from typing import Literal

from pydantic import BaseModel

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

    # Number of times pydantic-ai retries the LLM call when its output
    # fails to validate against the Abstract schema. Each retry appends
    # the validation error to the conversation, so the model gets a
    # chance to self-correct. The default of 1 (just one retry) is too
    # tight: a single off-by-one mistake from the model aborts the whole
    # file. 3 has been enough in practice for transient hiccups.
    llm_output_retries: int = 3
