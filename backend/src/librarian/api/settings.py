from pydantic import BaseModel

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


class Settings(YamlSettings):
    api: ApiSettings = ApiSettings()
    database: PostgresSettings = PostgresSettings()
    http_client: HttpClientSettings = HttpClientSettings()
    cookies: CookieSettings = CookieSettings()
    google_oauth: GoogleOAuthSettings = GoogleOAuthSettings()
    data_files: DataFilesSettings = DataFilesSettings()


settings = Settings()
