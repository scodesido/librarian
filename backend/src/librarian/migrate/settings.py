from librarian.settings.base import YamlSettings
from librarian.settings.postgres import PostgresSettings


class Settings(YamlSettings):
    dbmate_path: str = "/usr/local/bin/dbmate"
    database: PostgresSettings = PostgresSettings()


settings = Settings()
