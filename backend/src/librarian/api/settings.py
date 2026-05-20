from pydantic import BaseModel, SecretStr

from librarian.common.settings.base import YamlSettings
from librarian.common.settings.google_oauth import GoogleOAuthSettings
from librarian.common.settings.http_client import HttpClientSettings
from librarian.common.settings.postgres import PostgresSettings


class ApiSettings(BaseModel):
    host: str = "localhost"
    port: int = 8000
    reload: bool = False
    root_path: str = ""
    workers: int = 1
    cors_origins: list[str] = ["http://localhost:3000"]
    cors_headers: list[str] = ["Authorization"]
    cors_methods: list[str] = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


class CookieSettings(BaseModel):
    session_cookie_name: str = "session_id"


class DataFilesSettings(BaseModel):
    pipeline_counts_interval_seconds: float = 2.0


class QuerySettings(BaseModel):
    # Hard cap on the free-form question's length, applied at the endpoint
    # before any LLM call. Mirrored on the FE so the user gets immediate
    # feedback. Generous default; raise if real questions need it.
    question_max_chars: int = 1000

    # Per-call upper bound on how many node_ids the agent may pass to
    # `expand_nodes`. The agent is told this limit in its instructions; the
    # tool itself enforces it (returning an error the agent can recover from).
    tool_node_id_max_count: int = 3

    # Cap on how many blobs the final answer may carry. The agent is allowed
    # to return fewer; the endpoint truncates if it returns more.
    max_returned_blobs: int = 5

    # Defensive cap on `fetch_blob_contents` calls per request. The agent can
    # peek at blob content while exploring, but unbounded peeking would defeat
    # the descent-budget design — this caps the total number of blob-content
    # fetches in one query, separately from the descent budget.
    max_blob_content_fetches: int = 15

    # Descent budget = ceil(C * (root.height + 1)). With C=3 and a height-3
    # tree, the agent has 12 `expand_nodes` calls — enough to descend three
    # parallel branches with one branch revisit each.
    descent_budget_multiplier: float = 4.0

    # Heartbeat interval for the SSE stream when no events are pending, to
    # keep proxies from timing the connection out. The "step" / "descend" /
    # "done" events are pushed eagerly; this only kicks in between them.
    sse_heartbeat_seconds: float = 15.0

    # LLM model. Same "<provider>:<model>" shape as the other workers; today
    # supports "anthropic:..." and "ollama:..." via service/llm.py.
    llm_model: str = "anthropic:claude-haiku-4-5"
    llm_output_retries: int = 3

    # Separate model for the pre-flight search-terms extraction step. When
    # `search_terms` is not explicitly supplied on the request, the endpoint
    # runs a small no-tools agent on `question` to derive a sharper string
    # to embed (long, conversational questions otherwise pollute the query
    # vector). Defaults to the same model as the retrieval agent, but kept
    # as its own field so an operator can point extraction at a cheaper or
    # local model (e.g. ollama:qwen-small) without touching retrieval.
    # Reuses `anthropic_api_key` / `ollama_host` / `ollama_num_ctx` below.
    extract_llm_model: str = "anthropic:claude-haiku-4-5"
    extract_llm_output_retries: int = 3

    # Embedder used to score sibling children against the user's search terms.
    # The model and dimensions MUST match what `blob_extractor` was configured
    # with when the corpus was indexed — otherwise the query vector lives in a
    # different space and the similarity scores are meaningless. We deliberately
    # don't share a BaseModel with BlobExtractorSettings: the two are configured
    # independently in YAML and tying them at the schema level would only paper
    # over a constraint that's still the operator's responsibility.
    # Provider dispatch is the same "<provider>:<model>" shape used elsewhere;
    # today "ollama:..." and "voyageai:..." are wired up.
    embedding_model: str = "ollama:qwen3-embedding:0.6b"
    embedding_dimensions: int = 1024
    embedding_chunk_chars: int = 4000
    embedding_chunk_chars_max: int = 5000

    # Provider settings — only the one matching `llm_model`'s provider is
    # required. Mirrors the BlobExtractorSettings shape. `voyage_api_key` is
    # only required when `embedding_model` selects the voyageai provider.
    anthropic_api_key: SecretStr | None = None
    voyage_api_key: SecretStr | None = None
    ollama_host: str = "http://localhost:11434"
    ollama_num_ctx: int = 16384

    @property
    def get_anthropic_api_key(self) -> str:
        if self.anthropic_api_key is None:
            raise ValueError("query.anthropic_api_key is not configured")
        return self.anthropic_api_key.get_secret_value()

    @property
    def get_voyage_api_key(self) -> str:
        if self.voyage_api_key is None:
            raise ValueError("query.voyage_api_key is not configured")
        return self.voyage_api_key.get_secret_value()


class MCPSettings(BaseModel):
    # TODO: replace with proper per-user auth once claude.ai supports an auth
    # mechanism that works for us. Today the MCP endpoint is unauthenticated
    # (intended to be reached only through a private remote reverse-proxy);
    # every tool call runs as this configured user. Leaving this None makes
    # the tool fail at call time with a clear "MCP user_id not configured"
    # message rather than silently picking a user.
    user_id: int | None = None


class Settings(YamlSettings):
    api: ApiSettings = ApiSettings()
    database: PostgresSettings = PostgresSettings()
    http_client: HttpClientSettings = HttpClientSettings()
    cookies: CookieSettings = CookieSettings()
    google_oauth: GoogleOAuthSettings = GoogleOAuthSettings()
    data_files: DataFilesSettings = DataFilesSettings()
    query: QuerySettings = QuerySettings()
    mcp: MCPSettings = MCPSettings()


settings = Settings()
