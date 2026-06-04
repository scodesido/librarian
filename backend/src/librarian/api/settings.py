from pydantic import BaseModel, SecretStr

from librarian.common.settings.base import YamlSettings
from librarian.common.settings.embeddings import EmbeddingsSettings
from librarian.common.settings.google_oauth import GoogleOAuthSettings
from librarian.common.settings.http_client import HttpClientSettings
from librarian.common.settings.model_catalog import ModelCatalog
from librarian.common.settings.oauth_as import OAuthASSettings
from librarian.common.settings.ollama import OllamaSettings
from librarian.common.settings.postgres import PostgresSettings
from librarian.common.settings.user_tokens import UserTokensSettings


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


class AdminSettings(BaseModel):
    # Single shared password gating the /admin endpoints (the debug admin
    # panel: user selector + tree explorer). The panel itself sits behind
    # ssh, so this is a lightweight second gate, not a user/role system.
    # Left unset (None) the whole /admin surface refuses every request with
    # 503 — admin is opt-in per environment, never silently open.
    password: SecretStr | None = None


class DataFilesSettings(BaseModel):
    pipeline_counts_interval_seconds: float = 2.0


class QuerySettings(BaseModel):
    # Hard cap on the free-form question's length, applied at the endpoint
    # before any LLM call. Mirrored on the FE so the user gets immediate
    # feedback. Generous default; raise if real questions need it.
    question_max_chars: int = 1000

    # Per-call upper bound on how many node refs the agent may pass to
    # `list_children`. The agent is told this limit in its instructions; the
    # tool itself enforces it (returning an error the agent can recover from).
    tool_node_id_max_count: int = 3

    # Cap on how many blobs the final answer may carry. The agent is allowed
    # to return fewer; the endpoint truncates if it returns more.
    max_returned_blobs: int = 5

    # Defensive cap on `peek_blob` calls per request. The agent can peek at
    # blob content while exploring, but unbounded peeking would defeat the
    # descent-budget design — this caps the total number of blob-content
    # fetches in one query, separately from the descent budget.
    max_blob_content_fetches: int = 15

    # Defensive cap on `node_detail` calls per request (on-demand fetches of a
    # node's prose Abstract). Separate from the descent budget.
    max_node_detail_fetches: int = 15

    # Defensive cap on `blob_detail` calls per request (on-demand fetches of a
    # blob's prose Abstract — the cheap inspection tier the agent uses before
    # committing to a full-text `peek_blob`). Separate from the descent budget.
    max_blob_detail_fetches: int = 15

    # Defensive cap on `list_file_blobs` calls per request. Each call returns
    # one page; this bounds total paging across the query.
    max_file_blob_listings: int = 15

    # Page size for `list_file_blobs` — how many of a file's blob summaries are
    # returned per call. A file can hold many blobs, so the tool paginates; the
    # agent passes the returned `next_offset` to read more.
    file_blobs_page_size: int = 20

    # Descent budget = ceil(C * (root.height + 1)). With C=3 and a height-3
    # tree, the agent has 12 `list_children` calls — enough to descend three
    # parallel branches with one branch revisit each.
    descent_budget_multiplier: float = 4.0

    # Heartbeat interval for the SSE stream when no events are pending, to
    # keep proxies from timing the connection out. The "step" / "descend" /
    # "done" events are pushed eagerly; this only kicks in between them.
    sse_heartbeat_seconds: float = 15.0

    # pydantic-ai retry budgets. `llm_output_retries` covers the main
    # retrieval agent's FinalAnswer validation; `extract_llm_output_retries`
    # covers the smaller pre-flight extractor's ExtractedTerms.
    llm_output_retries: int = 3
    extract_llm_output_retries: int = 3


class Settings(YamlSettings):
    api: ApiSettings = ApiSettings()
    database: PostgresSettings = PostgresSettings()
    http_client: HttpClientSettings = HttpClientSettings()
    cookies: CookieSettings = CookieSettings()
    admin: AdminSettings = AdminSettings()
    google_oauth: GoogleOAuthSettings = GoogleOAuthSettings()
    data_files: DataFilesSettings = DataFilesSettings()
    query: QuerySettings = QuerySettings()
    # No default — the AS issuer URL has to be configured per environment
    # (see OAuthASSettings.public_base_url). The MCP endpoint and the SDK
    # auth routes will refuse to start without it.
    oauth_as: OAuthASSettings
    # Shared LLM/embedder runtime knobs and the per-user-token encryption
    # key. Identical YAML on the service side; see common/settings/*.
    ollama: OllamaSettings = OllamaSettings()
    embeddings: EmbeddingsSettings = EmbeddingsSettings()
    user_tokens: UserTokensSettings = UserTokensSettings()
    # Operator-defined whitelist of allowed models per slot, plus
    # defaults. No default — required configuration; the API will refuse
    # to start without it.
    model_catalog: ModelCatalog


settings = Settings()
