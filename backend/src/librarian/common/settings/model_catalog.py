from typing import Literal

from pydantic import BaseModel, model_validator

# Closed vocabulary of model "slots" — one per LLM/embedder seat the
# pipeline carries. Matches the CHECK on user_slot_tokens.slot and the
# field names of UserModelSettings. Adding a slot is a (migration,
# Pydantic, catalog) triple.
SlotName = Literal[
    "blob_llm",
    "node_llm_leaf",
    "node_llm_internal",
    "retrieval_llm",
    "extract_llm",
    "embedding",
]

SLOT_NAMES: tuple[SlotName, ...] = (
    "blob_llm",
    "node_llm_leaf",
    "node_llm_internal",
    "retrieval_llm",
    "extract_llm",
    "embedding",
)


def split_model(model: str) -> tuple[str, str]:
    """Parse a "<provider>:<model>" string. Raises ValueError on malformed
    input. Shared helper so the same parse lives in one place — the model
    catalog validates with it, the credential resolver dispatches on it,
    and the agent/embedder builders consume the parts.
    """
    if ":" not in model:
        raise ValueError(
            f"model {model!r} must be '<provider>:<model>' "
            "(e.g. 'anthropic:claude-haiku-4-5')"
        )
    provider, name = model.split(":", 1)
    return provider, name


def requires_token(model: str) -> bool:
    """True iff this model's provider needs a user-supplied API token.
    Today only `ollama` runs without one (operator-hosted, no auth);
    every other provider (anthropic, openai, xai, voyageai) requires
    the user to have a row in user_slot_tokens for the consuming slot.
    """
    provider, _ = split_model(model)
    return provider != "ollama"


class ModelOption(BaseModel):
    """One entry in a slot's `allowed` list. `label` is the human-readable
    name the FE shows in the dropdown; defaults to `model` when not set.
    """

    model: str
    label: str | None = None

    @property
    def display(self) -> str:
        return self.label if self.label is not None else self.model


class SlotCatalog(BaseModel):
    """The set of models the operator is willing to serve for one slot,
    plus the slot's fallback. `default` MUST appear in `allowed` — the
    validator below enforces that so a typo in YAML fails at startup,
    not at first user request.
    """

    allowed: list[ModelOption]
    default: str

    @model_validator(mode="after")
    def _default_in_allowed(self) -> "SlotCatalog":
        if not self.allowed:
            raise ValueError("SlotCatalog.allowed must not be empty")
        models = {opt.model for opt in self.allowed}
        if self.default not in models:
            raise ValueError(
                f"SlotCatalog.default {self.default!r} is not in allowed: "
                f"{sorted(models)}"
            )
        return self

    def contains(self, model: str) -> bool:
        return any(opt.model == model for opt in self.allowed)


class ModelCatalog(BaseModel):
    """Operator-defined whitelist of models per slot. Loaded from shared
    YAML by both api and service so the two processes agree on which
    models a user may pick and what the fallback is when a user's row
    is missing or carries a model the operator has since removed.

    Both processes use it for the same three jobs:
      1. Resolve a user's slot to a concrete model string (with fallback
         to `default` if the user's pick is no longer allowed).
      2. Validate an incoming user-settings PUT before persisting.
      3. (API only) Expose to the FE via /settings/catalog so the
         Settings tab renders the right dropdowns.
    """

    blob_llm: SlotCatalog
    node_llm_leaf: SlotCatalog
    node_llm_internal: SlotCatalog
    retrieval_llm: SlotCatalog
    extract_llm: SlotCatalog
    embedding: SlotCatalog

    def for_slot(self, slot: SlotName) -> SlotCatalog:
        # getattr keeps this method honest against future slot additions:
        # the Literal type means callers can't pass an unknown slot name,
        # and the model fields enumerate every legal value.
        slot_catalog: SlotCatalog = getattr(self, slot)
        return slot_catalog

    def resolve(self, slot: SlotName, user_choice: str | None) -> str:
        """Return the model string to actually use for `slot`. If the user
        picked something the operator still allows, honour it; otherwise
        fall back to the slot's `default` so a stale or absent user pick
        doesn't break iteration. The caller logs the fallback at the call
        site (we don't log here — the resolver is hot-path and silent).
        """
        slot_catalog = self.for_slot(slot)
        if user_choice is not None and slot_catalog.contains(user_choice):
            return user_choice
        return slot_catalog.default
