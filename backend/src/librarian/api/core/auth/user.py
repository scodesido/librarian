from typing import Annotated

from fastapi import Cookie, Depends, HTTPException

from librarian.api.core.db.connect import DbConnection
from librarian.api.core.db.tables.auth_sessions import AuthSessions
from librarian.api.settings import settings


async def current_user(
    conn: DbConnection,
    session_id: Annotated[
        str | None, Cookie(alias=settings.cookies.session_cookie_name)
    ] = None,
) -> int:
    if not session_id:
        raise HTTPException(status_code=401, detail="No session cookie")
    user_id = await AuthSessions(conn).resolve(session_id)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return user_id


CurrentUser = Annotated[int, Depends(current_user)]
