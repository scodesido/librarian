from fastapi import APIRouter

from librarian.api.core.auth.user import CurrentUser
from librarian.api.settings import settings
from librarian.common.settings.model_catalog import ModelCatalog

router = APIRouter(prefix="/settings/catalog")


@router.get("", response_model=ModelCatalog)
async def get_catalog(user_id: CurrentUser) -> ModelCatalog:
    """Return the operator-defined model catalog. The FE consumes this
    to populate the per-slot dropdowns in the Settings tab — the same
    `allowed` lists the PUT /settings/me handler validates against.

    Auth-gated: the catalog itself isn't sensitive, but the
    `CurrentUser` dependency keeps this consistent with every other
    settings endpoint (no public unauthenticated surface).
    """
    return settings.model_catalog
