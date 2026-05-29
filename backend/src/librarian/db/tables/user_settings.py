from datetime import datetime

from pydantic import BaseModel, field_validator

from librarian.common.settings.model_catalog import split_model
from librarian.db.table import Table, TableModel


class UserModelSettings(BaseModel):
    """The JSONB shape stored in user_settings.models. One string per slot;
    each must parse as '<provider>:<model>'. Whitelist enforcement (is this
    model in the operator's allowed list?) happens at the API layer using
    ModelCatalog — this class only validates the shape so a malformed
    string can't survive a round-trip through the DB.
    """

    blob_llm: str
    node_llm_leaf: str
    node_llm_internal: str
    retrieval_llm: str
    extract_llm: str
    embedding: str

    @field_validator(
        "blob_llm",
        "node_llm_leaf",
        "node_llm_internal",
        "retrieval_llm",
        "extract_llm",
        "embedding",
    )
    @classmethod
    def _shape(cls, value: str) -> str:
        split_model(value)
        return value


class UserSettingsModel(TableModel):
    user_id: int
    models: UserModelSettings
    created_at: datetime
    updated_at: datetime


class UserSettings(Table):
    async def get(self, user_id: int) -> UserSettingsModel | None:
        record = await self.conn.fetchrow(
            "SELECT user_id, models, created_at, updated_at "
            "FROM user_settings WHERE user_id = $1",
            user_id,
        )
        return UserSettingsModel.from_record(record)

    async def upsert(self, user_id: int, models: UserModelSettings) -> None:
        await self.conn.execute(
            "INSERT INTO user_settings (user_id, models) VALUES ($1, $2) "
            "ON CONFLICT (user_id) DO UPDATE SET models = EXCLUDED.models",
            user_id,
            models.model_dump(),
        )
