import asyncio
import json
from typing import Any, AsyncIterator

from aiohttp import ClientSession
from asyncpg import Pool
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from librarian.api.core.auth.user import CurrentUser
from librarian.api.db import DbConnection
from librarian.api.http import HttpClient
from librarian.api.settings import settings
from librarian.common.oauth.google.access import (
    NoGoogleAuthError,
    access_token_for_user,
)
from librarian.db.readiness import count_user_pipeline
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
        "fields": "nextPageToken,files(id,mimeType,name)",
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
    http: ClientSession, access_token: str, folder_id: str, base_path: str
) -> list[tuple[str, FileType, str]]:
    """Walk `folder_id` and its subfolders, returning each non-folder file as
    (drive_id, type, full_path). `full_path` is the file's folder path under
    the synced root, built from `base_path` plus each folder/file name as we
    descend (e.g. base "Research" -> "Research/2024/report.pdf").
    """
    queue: list[tuple[str, str]] = [(folder_id, base_path)]
    result: list[tuple[str, FileType, str]] = []
    while queue:
        current, prefix = queue.pop()
        for child in await list_folder_children(http, access_token, current):
            name = child["name"]
            child_path = f"{prefix}/{name}" if prefix else name
            if child["mimeType"] == DRIVE_FOLDER_MIME:
                queue.append((child["id"], child_path))
            else:
                result.append(
                    (child["id"], classify_mime(child["mimeType"]), child_path)
                )
    return result


async def list_drive_files(
    http: ClientSession, access_token: str, prefix: str
) -> list[tuple[str, FileType, str]]:
    # Always recurse from the resolved start folder (the Drive root for an
    # empty prefix). A flat listing would be one query for the whole drive,
    # but it returns files without their folder context, so it can't build the
    # full path we store as `name`. The recursive walk costs one query per
    # folder in exchange for correct paths everywhere.
    segments = normalize_prefix(prefix)
    folder_id = await resolve_folder_path(http, access_token, segments)
    if folder_id is None:
        raise HTTPException(
            status_code=404, detail=f"Prefix folder not found: {prefix}"
        )
    return await list_files_recursive(http, access_token, folder_id, "/".join(segments))


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
    try:
        access_token = await access_token_for_user(
            conn, http, settings.google_oauth, user_id
        )
    except NoGoogleAuthError as exc:
        raise HTTPException(
            status_code=401, detail="User not connected to Google"
        ) from exc
    items = await list_drive_files(http, access_token, body.prefix)
    if not items:
        raise HTTPException(
            status_code=404, detail=f"No files found under prefix: {body.prefix}"
        )
    paths = [drive_id for drive_id, _, _ in items]

    files = DataFiles(conn)
    async with conn.transaction():
        added = await files.insert_missing(user_id, "GDRIVE", items)
        removed = await files.delete_missing(user_id, "GDRIVE", paths)
    return SyncResponse(added=added, removed=removed)


@router.post("/rebuild-tree", status_code=204)
async def rebuild_tree(user_id: CurrentUser, conn: DbConnection) -> Response:
    """Drop every blob_edge for the user. The deferred orphan-collection
    trigger then walks the cascade up through data_nodes, collapsing the
    entire tree by commit time. Files and blobs are untouched, so the
    tree_builder/node_extractor workers rebuild from the existing blobs on
    their next poll.
    """
    async with conn.transaction():
        await conn.execute("DELETE FROM data_blob_edges WHERE user_id = $1", user_id)
    return Response(status_code=204)


@router.post("/clear", status_code=204)
async def clear(user_id: CurrentUser, conn: DbConnection) -> Response:
    """Drop every data_files row for the user. FK cascades remove
    data_blobs, data_blob_edges, and (via the orphan trigger) the whole
    tree. After this the library is empty; the user must POST /sync
    again to repopulate.

    Destructive: this discards all extracted blobs and LLM-generated
    abstracts. The caller is expected to confirm with the user.

    Named `/clear` rather than `/resync` because it does not, on its
    own, fetch anything from Drive — it only clears. Pairing a clear
    with a subsequent sync is left to the caller (typically the FE
    showing a "Hard re-sync" flow that POSTs both in sequence).
    """
    async with conn.transaction():
        await conn.execute("DELETE FROM data_files WHERE user_id = $1", user_id)
    return Response(status_code=204)


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
