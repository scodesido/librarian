from pydantic import BaseModel, SecretStr

from librarian.settings.base import YamlSettings
from librarian.settings.postgres import PostgresSettings


class ApiSettings(BaseModel):
    host: str = "localhost"
    port: int = 8000
    reload: bool = False
    root_path: str = ""
    workers: int = 1
    cors_origins: list[str] = ["http://localhost:3000"]
    cors_headers: list[str] = ["Authorization"]
    cors_methods: list[str] = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


class GoogleOAuthSettings(BaseModel):
    client_id: str | None = None
    client_secret: SecretStr | None = None
    scopes: list[str] = [
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/drive.readonly",
    ]

    auth_uri: str = "https://accounts.google.com/o/oauth2/auth"
    token_uri: str = "https://oauth2.googleapis.com/token"
    user_info_uri: str = "https://openidconnect.googleapis.com/v1/userinfo"

    token_encryption_key: SecretStr | None = None
    session_ttl_days: int = 1
    cookie_secure: bool = False
    post_login_redirect: str = "http://localhost:3000/"

    @property
    def get_client_id(self) -> str:
        if self.client_id is None:
            raise ValueError("Google OAUTH client_id is not configured")
        return self.client_id

    @property
    def get_client_secret(self) -> str:
        if self.client_secret is None:
            raise ValueError("Google OAUTH client_secret is not configured")
        return self.client_secret.get_secret_value()

    @property
    def get_token_encryption_key(self) -> str:
        if self.token_encryption_key is None:
            raise ValueError("Google OAUTH token_encryption_key is not configured")
        return self.token_encryption_key.get_secret_value()


class CookieSettings(BaseModel):
    session_cookie_name: str = "session_id"


class HttpClientSettings(BaseModel):
    timeout: float = 10.0
    pool_size: int = 10


class Settings(YamlSettings):
    api: ApiSettings = ApiSettings()
    database: PostgresSettings = PostgresSettings()
    http_client: HttpClientSettings = HttpClientSettings()
    cookies: CookieSettings = CookieSettings()
    google_oauth: GoogleOAuthSettings = GoogleOAuthSettings()


settings = Settings()
