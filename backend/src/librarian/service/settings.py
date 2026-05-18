from pydantic import BaseModel

from librarian.common.settings.base import YamlSettings
from librarian.common.settings.google_oauth import GoogleOAuthSettings
from librarian.common.settings.http_client import HttpClientSettings
from librarian.common.settings.postgres import PostgresSettings
from librarian.service.blob_extractor.settings import BlobExtractorSettings


class GlobalServiceSettings(BaseModel):
    autoreload: bool = False


class Settings(YamlSettings):
    service: GlobalServiceSettings = GlobalServiceSettings()
    database: PostgresSettings = PostgresSettings()
    http_client: HttpClientSettings = HttpClientSettings()
    google_oauth: GoogleOAuthSettings = GoogleOAuthSettings()
    blob_extractor: BlobExtractorSettings = BlobExtractorSettings()


settings = Settings()
