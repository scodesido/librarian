from pydantic import BaseModel

from librarian.service.blob_reader.settings import BlobReaderSettings
from librarian.settings.base import YamlSettings
from librarian.settings.google_oauth import GoogleOAuthSettings
from librarian.settings.http_client import HttpClientSettings
from librarian.settings.postgres import PostgresSettings


class GlobalServiceSettings(BaseModel):
    autoreload: bool = False


class Settings(YamlSettings):
    service: GlobalServiceSettings = GlobalServiceSettings()
    database: PostgresSettings = PostgresSettings()
    http_client: HttpClientSettings = HttpClientSettings()
    google_oauth: GoogleOAuthSettings = GoogleOAuthSettings()
    blob_reader: BlobReaderSettings = BlobReaderSettings()


settings = Settings()
