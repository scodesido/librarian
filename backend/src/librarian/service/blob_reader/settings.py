from pydantic import BaseModel, SecretStr


class BlobReaderSettings(BaseModel):
    # Worker loop
    poll_interval_seconds: float = 2.0
    claim_timeout_seconds: float = 600.0
    concurrent_workers: int = 1

    # Chunking
    pages_per_blob: int = 10
    words_per_blob: int = 1500

    # Abstract shape
    summary_words: int = 100
    topics_count: int = 5
    running_summary_words: int = 80

    # Models (pydantic-ai model strings: "<provider>:<model>")
    llm_model: str = "anthropic:claude-haiku-4-5"
    embedding_model: str = "voyageai:voyage-4"

    # Which Abstract fields get embedded (keys of Abstract). Other fields
    # are stored in the JSONB but not vector-indexed.
    embedded_fields: list[str] = ["summary", "topics", "running_summary"]

    # API keys passed explicitly to the providers (rather than letting the
    # SDKs read them from env). This is the seam that will later carry
    # values mounted as secret files.
    anthropic_api_key: SecretStr | None = None
    voyage_api_key: SecretStr | None = None

    @property
    def get_anthropic_api_key(self) -> str:
        if self.anthropic_api_key is None:
            raise ValueError("blob_reader.anthropic_api_key is not configured")
        return self.anthropic_api_key.get_secret_value()

    @property
    def get_voyage_api_key(self) -> str:
        if self.voyage_api_key is None:
            raise ValueError("blob_reader.voyage_api_key is not configured")
        return self.voyage_api_key.get_secret_value()
