from librarian.common.settings.base import YamlSettings
from librarian.common.settings.postgres import PostgresSettings


class Settings(YamlSettings):
    dbmate_path: str = "/usr/local/bin/dbmate"
    database: PostgresSettings = PostgresSettings()


settings = Settings()
