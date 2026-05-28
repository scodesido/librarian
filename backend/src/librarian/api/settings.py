from pydantic import BaseModel, SecretStr

from librarian.common.settings.base import YamlSettings
from librarian.common.settings.google_oauth import GoogleOAuthSettings
from librarian.common.settings.http_client import HttpClientSettings
from librarian.common.settings.oauth_as import OAuthASSettings
from librarian.common.settings.postgres import PostgresSettings


class ApiSettings(BaseModel):
    host: str = "localhost"
    port: int = 8000
    reload: bool = False
    workers: int = 1
    cors_origins: list[str] = ["http://localhost:3000"]
    cors_headers: list[str] = ["Authorization"]
    cors_methods: list[str] = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]

    # Trust `X-Forwarded-*` headers when behind a reverse proxy. Required
    # for `request.url_for(...)` (and the absolute URLs we hand to Google
    # / MCP clients) to come out with the right scheme+host when the
    # process is reached through nginx. Off by default so a directly
    # exposed dev server cannot be spoofed by header injection.
    uvicorn_proxy_headers: bool = False
    # Comma-separated list of IPs (or "*") whose forwarded headers we
    # trust. Default matches uvicorn's own default — only the local
    # reverse proxy.
    uvicorn_forwarded_allow_ips: str = "127.0.0.1"


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

    # LLM model. Same "<provider>:<model>" shape as the other workers;
    # today supports "anthropic:...", "openai:...", "xai:..." and
    # "ollama:..." via service/llm.py.
    llm_model: str = "anthropic:claude-haiku-4-5"
    llm_output_retries: int = 3

    # Separate model for the pre-flight search-terms extraction step. When
    # `search_terms` is not explicitly supplied on the request, the endpoint
    # runs a small no-tools agent on `question` to derive a sharper string
    # to embed (long, conversational questions otherwise pollute the query
    # vector). Defaults to the same model as the retrieval agent, but kept
    # as its own field so an operator can point extraction at a cheaper or
    # local model (e.g. ollama:qwen-small) without touching retrieval.
    # Reuses `llm_api_token` / `ollama_host` / `ollama_num_ctx` below.
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

    # API tokens — one per slot. `llm_api_token` covers both the
    # retrieval agent's LLM and the pre-flight extraction LLM (the two
    # share the same token in practice — same provider with different
    # model sizes if anything). `embedder_api_token` covers the
    # similarity-scoring embedder. Mirrors the BlobExtractorSettings
    # shape. Either is unused for providers that need no auth (ollama).
    # `embedder_api_token` is only required when `embedding_model`
    # selects the voyageai provider.
    llm_api_token: SecretStr | None = None
    embedder_api_token: SecretStr | None = None
    ollama_host: str = "http://localhost:11434"
    ollama_num_ctx: int = 16384

    @property
    def get_embedder_api_token(self) -> str:
        if self.embedder_api_token is None:
            raise ValueError("query.embedder_api_token is not configured")
        return self.embedder_api_token.get_secret_value()


class Settings(YamlSettings):
    api: ApiSettings = ApiSettings()
    database: PostgresSettings = PostgresSettings()
    http_client: HttpClientSettings = HttpClientSettings()
    cookies: CookieSettings = CookieSettings()
    google_oauth: GoogleOAuthSettings = GoogleOAuthSettings()
    data_files: DataFilesSettings = DataFilesSettings()
    query: QuerySettings = QuerySettings()
    # No default — the AS issuer URL has to be configured per environment
    # (see OAuthASSettings.public_base_url). The MCP endpoint and the SDK
    # auth routes will refuse to start without it.
    oauth_as: OAuthASSettings


settings = Settings()
