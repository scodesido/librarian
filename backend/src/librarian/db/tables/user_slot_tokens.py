from datetime import datetime

from librarian.common.settings.model_catalog import SlotName
from librarian.db.table import Table, TableModel


class UserSlotTokensModel(TableModel):
    user_id: int
    slot: SlotName
    token_enc: bytes
    created_at: datetime
    updated_at: datetime


class UserSlotTokens(Table):
    async def get(self, user_id: int, slot: SlotName) -> UserSlotTokensModel | None:
        record = await self.conn.fetchrow(
            "SELECT user_id, slot, token_enc, created_at, updated_at "
            "FROM user_slot_tokens WHERE user_id = $1 AND slot = $2",
            user_id,
            slot,
        )
        return UserSlotTokensModel.from_record(record)

    async def get_all(self, user_id: int) -> list[UserSlotTokensModel]:
        rows = await self.conn.fetch(
            "SELECT user_id, slot, token_enc, created_at, updated_at "
            "FROM user_slot_tokens WHERE user_id = $1",
            user_id,
        )
        return [UserSlotTokensModel.model_validate(dict(r)) for r in rows]

    async def present_slots(self, user_id: int) -> list[SlotName]:
        rows = await self.conn.fetch(
            "SELECT slot FROM user_slot_tokens WHERE user_id = $1",
            user_id,
        )
        return [row["slot"] for row in rows]

    async def upsert(self, user_id: int, slot: SlotName, token_enc: bytes) -> None:
        await self.conn.execute(
            "INSERT INTO user_slot_tokens (user_id, slot, token_enc) "
            "VALUES ($1, $2, $3) "
            "ON CONFLICT (user_id, slot) DO UPDATE SET token_enc = EXCLUDED.token_enc",
            user_id,
            slot,
            token_enc,
        )

    async def delete(self, user_id: int, slot: SlotName) -> None:
        await self.conn.execute(
            "DELETE FROM user_slot_tokens WHERE user_id = $1 AND slot = $2",
            user_id,
            slot,
        )
