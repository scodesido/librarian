from fastapi import APIRouter
from pydantic import BaseModel, Field

from librarian.api.core.auth.user import CurrentUser
from librarian.api.db import DbConnection
from librarian.api.settings import settings
from librarian.common.crypto.fernet import encrypt as fernet_encrypt
from librarian.common.settings.model_catalog import SLOT_NAMES, SlotName
from librarian.db.tables.user_slot_tokens import UserSlotTokens

router = APIRouter(prefix="/settings/tokens")


class SlotStatus(BaseModel):
    """Per-slot token presence. The token value itself is never
    returned — encrypted-at-rest tokens are write-only from the
    FE's perspective; the only readable state is "saved" vs "not".
    """

    slot: SlotName
    has_token: bool


class TokensResponse(BaseModel):
    slots: list[SlotStatus]


class PutTokenBody(BaseModel):
    token: str = Field(min_length=1)


@router.get("", response_model=TokensResponse)
async def list_tokens(user_id: CurrentUser, conn: DbConnection) -> TokensResponse:
    """One row per slot, in catalog order. has_token reflects whether
    a user_slot_tokens row exists; the encrypted value never leaves
    the DB.
    """
    present = set(await UserSlotTokens(conn).present_slots(user_id))
    return TokensResponse(
        slots=[SlotStatus(slot=slot, has_token=slot in present) for slot in SLOT_NAMES]
    )


@router.put("/{slot}", status_code=204)
async def put_token(
    user_id: CurrentUser,
    conn: DbConnection,
    slot: SlotName,
    body: PutTokenBody,
) -> None:
    """Encrypt the user-supplied token with the operator's Fernet key
    and upsert the row. The plaintext never reaches storage; the
    operator-side key is the only thing that can decrypt the resulting
    bytes — a DB leak should not become a credential leak.
    """
    enc = fernet_encrypt(settings.user_tokens.get_encryption_key, body.token)
    await UserSlotTokens(conn).upsert(user_id, slot, enc)


@router.delete("/{slot}", status_code=204)
async def delete_token(
    user_id: CurrentUser,
    conn: DbConnection,
    slot: SlotName,
) -> None:
    await UserSlotTokens(conn).delete(user_id, slot)
