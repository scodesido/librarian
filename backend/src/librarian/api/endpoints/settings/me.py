from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from librarian.api.core.auth.user import CurrentUser
from librarian.api.db import DbConnection
from librarian.api.settings import settings
from librarian.common.settings.model_catalog import SLOT_NAMES
from librarian.db.tables.user_settings import UserModelSettings, UserSettings

router = APIRouter(prefix="/settings/me")


class MeResponse(BaseModel):
    """Effective per-user settings: the user's saved choices with
    catalog defaults filled in for slots they haven't touched (or
    slots whose previously-saved model the operator has since removed
    from `allowed`). The FE renders dropdowns straight off `models` —
    every field is always populated.
    """

    models: UserModelSettings


@router.get("", response_model=MeResponse)
async def get_me(user_id: CurrentUser, conn: DbConnection) -> MeResponse:
    saved = await UserSettings(conn).get(user_id)
    catalog = settings.model_catalog
    if saved is None:
        models = UserModelSettings(
            blob_llm=catalog.blob_llm.default,
            node_llm_leaf=catalog.node_llm_leaf.default,
            node_llm_internal=catalog.node_llm_internal.default,
            retrieval_llm=catalog.retrieval_llm.default,
            extract_llm=catalog.extract_llm.default,
            embedding=catalog.embedding.default,
        )
    else:
        models = UserModelSettings(
            blob_llm=catalog.resolve("blob_llm", saved.models.blob_llm),
            node_llm_leaf=catalog.resolve("node_llm_leaf", saved.models.node_llm_leaf),
            node_llm_internal=catalog.resolve(
                "node_llm_internal", saved.models.node_llm_internal
            ),
            retrieval_llm=catalog.resolve("retrieval_llm", saved.models.retrieval_llm),
            extract_llm=catalog.resolve("extract_llm", saved.models.extract_llm),
            embedding=catalog.resolve("embedding", saved.models.embedding),
        )
    return MeResponse(models=models)


@router.put("", status_code=204)
async def put_me(
    user_id: CurrentUser,
    conn: DbConnection,
    body: UserModelSettings,
) -> None:
    """Validate the chosen models against the operator's catalog, then
    persist. Each slot's chosen model must appear in the catalog's
    `allowed` list for that slot — a user picking an off-list model
    is rejected with 400 naming the slot.

    Token availability is intentionally NOT validated here: the user
    may want to save their settings before adding tokens, or may have
    legitimate reasons to save a token-requiring model with no token
    (e.g. they're about to add it). Workers/retrieval surface the
    missing token as a 409 when the model is actually used.
    """
    catalog = settings.model_catalog
    for slot in SLOT_NAMES:
        chosen = getattr(body, slot)
        if not catalog.for_slot(slot).contains(chosen):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"slot {slot!r}: model {chosen!r} is not in the "
                    "operator's allowed list for this slot"
                ),
            )
    await UserSettings(conn).upsert(user_id, body)
