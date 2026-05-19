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
    max_blob_content_fetches: int = 10

    # Descent budget = ceil(C * (root.height + 1)). With C=3 and a height-3
    # tree, the agent has 12 `expand_nodes` calls — enough to descend three
    # parallel branches with one branch revisit each.
    descent_budget_multiplier: float = 3.0

    # Heartbeat interval for the SSE stream when no events are pending, to
    # keep proxies from timing the connection out. The "step" / "descend" /
    # "done" events are pushed eagerly; this only kicks in between them.
    sse_heartbeat_seconds: float = 15.0

    # LLM model. Same "<provider>:<model>" shape as the other workers; today
    # supports "anthropic:..." and "ollama:..." via service/llm.py.
    llm_model: str = "anthropic:claude-haiku-4-5"
    llm_output_retries: int = 3

    # Provider settings — only the one matching `llm_model`'s provider is
    # required. Mirrors the BlobExtractorSettings shape.
    anthropic_api_key: SecretStr | None = None
    ollama_host: str = "http://localhost:11434"
    ollama_num_ctx: int = 16384

    @property
    def get_anthropic_api_key(self) -> str:
        if self.anthropic_api_key is None:
            raise ValueError("query.anthropic_api_key is not configured")
        return self.anthropic_api_key.get_secret_value()


class Settings(YamlSettings):
    api: ApiSettings = ApiSettings()
    database: PostgresSettings = PostgresSettings()
    http_client: HttpClientSettings = HttpClientSettings()
    cookies: CookieSettings = CookieSettings()
    google_oauth: GoogleOAuthSettings = GoogleOAuthSettings()
    data_files: DataFilesSettings = DataFilesSettings()
    query: QuerySettings = QuerySettings()


settings = Settings()
