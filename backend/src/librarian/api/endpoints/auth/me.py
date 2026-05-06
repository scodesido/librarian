from fastapi import APIRouter
from pydantic import BaseModel

from librarian.api.core.auth.user import CurrentUser
from librarian.api.core.db.connect import DbConnection
from librarian.api.core.db.tables.auth_google import AuthGoogle

router = APIRouter(prefix="/auth")


class GoogleIdentity(BaseModel):
    sub: str
    email: str


class MeResponse(BaseModel):
    user_id: int
    google: GoogleIdentity | None = None


@router.get("/me", response_model=MeResponse)
async def me(user_id: CurrentUser, conn: DbConnection) -> MeResponse:
    auth = await AuthGoogle(conn).for_user(user_id)
    google = (
        GoogleIdentity(sub=auth.sub, email=auth.email) if auth is not None else None
    )
    return MeResponse(user_id=user_id, google=google)
