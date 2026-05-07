from pydantic import BaseModel

from librarian.settings.base import YamlSettings


class BlobReaderSettings(BaseModel):
    pass


class Settings(YamlSettings):
    blob_reader: BlobReaderSettings = BlobReaderSettings()


settings = Settings()
