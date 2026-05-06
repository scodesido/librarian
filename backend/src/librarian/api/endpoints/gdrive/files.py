from typing import Any

from fastapi import APIRouter, HTTPException

from librarian.api.core.auth.user import CurrentUser
from librarian.api.core.db.connect import DbConnection
from librarian.api.core.db.tables.auth_google import AuthGoogle
from librarian.api.core.http.client import HttpClient
from librarian.api.core.oauth.google.tokens import refresh_access_token

DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"

router = APIRouter(prefix="/gdrive/files")


@router.get("/")
async def list_files(
    user_id: CurrentUser,
    conn: DbConnection,
    http: HttpClient,
) -> dict[str, Any]:
    auth = await AuthGoogle(conn).for_user(user_id)
    if auth is None:
        raise HTTPException(status_code=401, detail="User not connected to Google")

    access_token = await refresh_access_token(http, auth.refresh_token)

    async with http.get(
        DRIVE_FILES_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "q": "trashed = false",
            "pageSize": 50,
            "fields": "files(id,name,mimeType,modifiedTime)",
        },
    ) as resp:
        resp.raise_for_status()
        body: dict[str, Any] = await resp.json()
    return body
