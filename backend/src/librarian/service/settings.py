from pydantic import BaseModel

from librarian.settings.base import YamlSettings


class GlobalServiceSettings(BaseModel):
    autoreload: bool = False


class Settings(YamlSettings):
    service: GlobalServiceSettings = GlobalServiceSettings()


settings = Settings()
