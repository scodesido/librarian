from pathlib import Path
from typing import Tuple, Type

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


class SettingsFileSettings(BaseSettings):
    yaml_settings_file: Path = Path("/app/config/settings.yaml")
    yaml_settings_extra_files: list[Path] = []

    model_config = SettingsConfigDict(
        env_prefix="LIBRARIAN__",
        case_sensitive=False,
    )


settings_files = SettingsFileSettings()


class YamlSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LIBRARIAN__",
        env_nested_delimiter="__",
        yaml_file=str(settings_files.yaml_settings_file.resolve()),
        case_sensitive=False,
        nested_model_default_partial_update=True,
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        yaml_settings_files = settings_files.yaml_settings_extra_files[::-1] + [
            settings_files.yaml_settings_file
        ]
        yaml_settings_sources = [
            YamlConfigSettingsSource(settings_cls, file) for file in yaml_settings_files
        ]

        return (
            init_settings,
            env_settings,
            *yaml_settings_sources,
        )
