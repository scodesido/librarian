import asyncio
import json
from typing import Any, AsyncIterator

from aiohttp import ClientSession
from asyncpg import Pool
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from librarian.api.core.auth.user import CurrentUser
from librarian.api.db import DbConnection
from librarian.api.http import HttpClient
from librarian.api.settings import settings
from librarian.common.oauth.google.crypto import decrypt as decrypt_google_token
from librarian.common.oauth.google.tokens import refresh_access_token
from librarian.db.readiness import count_user_pipeline
from librarian.db.tables.auth_google import AuthGoogle
from librarian.db.tables.data_files import DataFiles, FileType

DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
DRIVE_PAGE_SIZE = 1000
DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"
DRIVE_ROOT = "root"

router = APIRouter(prefix="/data/files")


class SyncRequest(BaseModel):
    prefix: str = "/"


class SyncResponse(BaseModel):
    added: int
    removed: int


def classify_mime(mime: str) -> FileType:
    if mime == "application/pdf":
        return "PDF"
    if mime.startswith("text/"):
        return "TEXT"
    return "OTHER"


def normalize_prefix(prefix: str) -> list[str]:
    return [s for s in prefix.strip().strip("/").split("/") if s]


def escape_drive_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


async def fetch_drive_page(
    http: ClientSession,
    access_token: str,
    q: str,
    page_token: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "q": q,
        "pageSize": DRIVE_PAGE_SIZE,
        "fields": "nextPageToken,files(id,mimeType)",
    }
    if page_token is not None:
        params["pageToken"] = page_token
    async with http.get(
        DRIVE_FILES_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        params=params,
    ) as resp:
        resp.raise_for_status()
        body: dict[str, Any] = await resp.json()
    return body


async def find_subfolder(
    http: ClientSession, access_token: str, parent_id: str, name: str
) -> str | None:
    q = (
        f"trashed = false and mimeType = '{DRIVE_FOLDER_MIME}' "
        f"and '{parent_id}' in parents and name = '{escape_drive_literal(name)}'"
    )
    body = await fetch_drive_page(http, access_token, q)
    files = body.get("files", [])
    if not files:
        return None
    folder_id: str = files[0]["id"]
    return folder_id


async def resolve_folder_path(
    http: ClientSession, access_token: str, segments: list[str]
) -> str | None:
    folder_id = DRIVE_ROOT
    for segment in segments:
        next_id = await find_subfolder(http, access_token, folder_id, segment)
        if next_id is None:
            return None
        folder_id = next_id
    return folder_id


async def list_folder_children(
    http: ClientSession, access_token: str, folder_id: str
) -> list[dict[str, str]]:
    q = f"trashed = false and '{folder_id}' in parents"
    items: list[dict[str, str]] = []
    page_token: str | None = None
    while True:
        body = await fetch_drive_page(http, access_token, q, page_token)
        items.extend(body.get("files", []))
        page_token = body.get("nextPageToken")
        if not page_token:
            return items


async def list_files_recursive(
    http: ClientSession, access_token: str, folder_id: str
) -> list[tuple[str, FileType]]:
    queue: list[str] = [folder_id]
    result: list[tuple[str, FileType]] = []
    while queue:
        current = queue.pop()
        for child in await list_folder_children(http, access_token, current):
            if child["mimeType"] == DRIVE_FOLDER_MIME:
                queue.append(child["id"])
            else:
                result.append((child["id"], classify_mime(child["mimeType"])))
    return result


async def list_drive_files_flat(
    http: ClientSession, access_token: str
) -> list[tuple[str, FileType]]:
    q = f"trashed = false and mimeType != '{DRIVE_FOLDER_MIME}'"
    items: list[tuple[str, FileType]] = []
    page_token: str | None = None
    while True:
        body = await fetch_drive_page(http, access_token, q, page_token)
        for child in body.get("files", []):
            items.append((child["id"], classify_mime(child["mimeType"])))
        page_token = body.get("nextPageToken")
        if not page_token:
            return items


async def list_drive_files(
    http: ClientSession, access_token: str, prefix: str
) -> list[tuple[str, FileType]]:
    segments = normalize_prefix(prefix)
    if not segments:
        return await list_drive_files_flat(http, access_token)
    folder_id = await resolve_folder_path(http, access_token, segments)
    if folder_id is None:
        raise HTTPException(
            status_code=404, detail=f"Prefix folder not found: {prefix}"
        )
    return await list_files_recursive(http, access_token, folder_id)


# TODO: also fetch modifiedTime from Drive and pass it through to
# data_files.source_modified_at. On a second sync pass, compare it against
# the stored value: if Drive's is newer, delete the row (cascading blobs +
# tree edges via the FK chain) and let insert_missing pick it up fresh. The
# column is already in the schema; only the sync layer and DataFiles
# accessor need to grow this branch.
@router.post("/sync", response_model=SyncResponse)
async def sync(
    user_id: CurrentUser,
    conn: DbConnection,
    http: HttpClient,
    body: SyncRequest,
) -> SyncResponse:
    auth = await AuthGoogle(conn).for_user(user_id)
    if auth is None:
        raise HTTPException(status_code=401, detail="User not connected to Google")

    refresh_token = decrypt_google_token(
        settings.google_oauth.get_token_encryption_key, auth.refresh_token_enc
    )
    access_token = await refresh_access_token(
        http, settings.google_oauth, refresh_token
    )
    items = await list_drive_files(http, access_token, body.prefix)
    if not items:
        raise HTTPException(
            status_code=404, detail=f"No files found under prefix: {body.prefix}"
        )
    paths = [path for path, _ in items]

    files = DataFiles(conn)
    async with conn.transaction():
        added = await files.insert_missing(user_id, "GDRIVE", items)
        removed = await files.delete_missing(user_id, "GDRIVE", paths)
    return SyncResponse(added=added, removed=removed)


async def pipeline_counts_events(
    pool: Pool, user_id: int, interval: float
) -> AsyncIterator[bytes]:
    while True:
        async with pool.acquire() as conn:
            counts = await count_user_pipeline(conn, user_id)
        yield f"data: {json.dumps(counts.model_dump())}\n\n".encode()
        await asyncio.sleep(interval)


@router.get("/pipeline-counts/stream")
async def pipeline_counts_stream(
    user_id: CurrentUser, request: Request
) -> StreamingResponse:
    pool: Pool | None = request.app.state.db_connection_pool
    if pool is None:
        raise ValueError("No database connection pool available")
    return StreamingResponse(
        pipeline_counts_events(
            pool, user_id, settings.data_files.pipeline_counts_interval_seconds
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
