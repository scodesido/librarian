from dataclasses import dataclass

from asyncpg.pool import PoolConnectionProxy

from librarian.common.crypto.fernet import decrypt as fernet_decrypt
from librarian.common.settings.model_catalog import (
    SLOT_NAMES,
    ModelCatalog,
    SlotName,
    requires_token,
)
from librarian.common.settings.ollama import OllamaSettings
from librarian.common.settings.user_tokens import UserTokensSettings
from librarian.db.tables.user_settings import UserSettings
from librarian.db.tables.user_slot_tokens import UserSlotTokens


class MissingTokenError(Exception):
    """Raised by `resolve_user_credentials` when a user picked (or the
    catalog defaulted them onto) a model that requires a token, but no row
    exists for that slot in `user_slot_tokens`. Workers catch this to skip
    the user without burning the exponential-backoff curve (the issue is
    user-config, not system); API endpoints surface it as 409.
    """

    def __init__(self, slot: SlotName, model: str) -> None:
        super().__init__(
            f"slot {slot!r} resolves to model {model!r}, which requires an "
            f"API token, but no row exists in user_slot_tokens for this slot"
        )
        self.slot = slot
        self.model = model


@dataclass(frozen=True)
class ModelCreds:
    """Resolved credentials for one slot, ready to hand to the LLM/embedder
    builders. `api_token` is the decrypted user token (None for ollama).
    `ollama_host` / `ollama_num_ctx` are the operator-side ollama runtime
    knobs — kept on every ModelCreds even when the slot doesn't need
    ollama so the build-side dispatch can read what it needs without
    extra threading.
    """

    model: str
    api_token: str | None
    ollama_host: str
    ollama_num_ctx: int


@dataclass(frozen=True)
class UserCredentials:
    """The six per-slot resolved credentials, bundled. Workers consume two
    or three slots; the retrieval endpoint consumes two; building all six
    up-front keeps the resolver call to one round trip and lets a future
    cross-slot validation (e.g. "extract and retrieval must point at the
    same provider for prompt caching to hit") be a pure function on the
    bundle.
    """

    blob_llm: ModelCreds
    node_llm_leaf: ModelCreds
    node_llm_internal: ModelCreds
    retrieval_llm: ModelCreds
    extract_llm: ModelCreds
    embedding: ModelCreds

    def for_slot(self, slot: SlotName) -> ModelCreds:
        creds: ModelCreds = getattr(self, slot)
        return creds


async def resolve_user_credentials(
    conn: PoolConnectionProxy,
    user_id: int,
    catalog: ModelCatalog,
    ollama: OllamaSettings,
    user_tokens: UserTokensSettings,
) -> UserCredentials:
    """Load a user's settings + tokens, resolve each slot to a concrete
    model via the catalog (falling back to the slot's default if the user
    has no row or picked a model the operator no longer allows), and
    decrypt the token for every non-ollama slot. Raises MissingTokenError
    on the first slot whose resolved model needs a token the user hasn't
    saved.

    Two queries (settings row + tokens for the user). Cost is small
    relative to the per-iteration LLM/network work, so we don't cache
    across iterations — each iteration sees whatever the user most
    recently saved.
    """
    settings_row = await UserSettings(conn).get(user_id)
    user_models = settings_row.models if settings_row is not None else None

    token_rows = await UserSlotTokens(conn).get_all(user_id)
    tokens_by_slot: dict[str, bytes] = {row.slot: row.token_enc for row in token_rows}

    by_slot: dict[str, ModelCreds] = {}
    for slot in SLOT_NAMES:
        user_choice = getattr(user_models, slot) if user_models is not None else None
        resolved_model = catalog.resolve(slot, user_choice)
        api_token: str | None = None
        if requires_token(resolved_model):
            token_enc = tokens_by_slot.get(slot)
            if token_enc is None:
                raise MissingTokenError(slot, resolved_model)
            api_token = fernet_decrypt(user_tokens.get_encryption_key, token_enc)
        by_slot[slot] = ModelCreds(
            model=resolved_model,
            api_token=api_token,
            ollama_host=ollama.host,
            ollama_num_ctx=ollama.num_ctx,
        )
    return UserCredentials(
        blob_llm=by_slot["blob_llm"],
        node_llm_leaf=by_slot["node_llm_leaf"],
        node_llm_internal=by_slot["node_llm_internal"],
        retrieval_llm=by_slot["retrieval_llm"],
        extract_llm=by_slot["extract_llm"],
        embedding=by_slot["embedding"],
    )
