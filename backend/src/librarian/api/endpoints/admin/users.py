from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from librarian.api.core.auth.admin import require_admin
from librarian.api.db import DbConnection
from librarian.db.tables.users import Users

router = APIRouter(prefix="/admin/users", dependencies=[Depends(require_admin)])


class AdminUser(BaseModel):
    user_id: int
    user_name: str
    created_at: datetime


class UsersResponse(BaseModel):
    users: list[AdminUser]


@router.get("", response_model=UsersResponse)
async def list_users(conn: DbConnection) -> UsersResponse:
    """All users, for the admin panel's user selector. `user_name` is the
    Google email captured at sign-up (see oauth/google), enough to tell
    accounts apart when debugging another user's tree.
    """
    rows = await Users(conn).list_all()
    return UsersResponse(
        users=[
            AdminUser(user_id=u.id, user_name=u.user_name, created_at=u.created_at)
            for u in rows
        ]
    )
