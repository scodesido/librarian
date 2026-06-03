from dataclasses import dataclass, field
from typing import Protocol

from aiohttp import ClientSession
from asyncpg.pool import PoolConnectionProxy

from librarian.common.oauth.google.access import access_token_for_user
from librarian.common.settings.google_oauth import GoogleOAuthSettings
from librarian.db.tables.data_files import FileSource, FileType
from librarian.service.blob_extractor.drive import download_file
from librarian.service.blob_extractor.pdf_text import (
    extract_pdf_pages_bytes,
    extract_pdf_pages_text,
)


@dataclass(frozen=True)
class BlobLocator:
    """Everything a provider needs to materialise the plaintext for one blob.

    `source_path` is the upstream identifier (Drive file_id for GDRIVE), not
    the data_files PK. `file_start` and `file_end` are the blob's half-open
    range — page indices for PDF, character offsets for TEXT.
    """

    file_id: int
    source: FileSource
    source_path: str
    type: FileType
    file_start: int
    file_end: int


class BlobContentProvider(Protocol):
    """Per-source plaintext fetcher. One instance per request, scoped to one
    user. Implementations are expected to cache the underlying source file
    by `source_path` so that two blobs from the same file share a single
    download.
    """

    async def fetch_text(self, blob: BlobLocator) -> str: ...

    async def fetch_bytes(self, blob: BlobLocator) -> tuple[bytes, str]:
        """Materialise the blob's original bytes plus a MIME type, for the
        retrieval binary-output mode. Same source-range semantics as
        `fetch_text`, but preserves the original representation (e.g. the PDF
        page range as a standalone PDF) instead of extracting plaintext.
        """
        ...


class UnsupportedBlobTypeError(Exception):
    pass


@dataclass
class GDriveBlobProvider:
    """Downloads each Drive file once per request and slices it locally.

    The provider holds the user's access_token (resolved once via
    `access_token_for_user`) and an in-memory cache keyed by Drive file_id.
    The cache lifetime is the request — there is no cross-request sharing.
    """

    http: ClientSession
    access_token: str
    _downloads: dict[str, bytes] = field(default_factory=dict)

    async def _file_bytes(self, source_path: str) -> bytes:
        cached = self._downloads.get(source_path)
        if cached is not None:
            return cached
        data = await download_file(self.http, self.access_token, source_path)
        self._downloads[source_path] = data
        return data

    async def fetch_text(self, blob: BlobLocator) -> str:
        data = await self._file_bytes(blob.source_path)
        if blob.type == "PDF":
            return extract_pdf_pages_text(data, blob.file_start, blob.file_end)
        if blob.type == "TEXT":
            text = data.decode("utf-8", errors="replace")
            return text[blob.file_start : blob.file_end]
        raise UnsupportedBlobTypeError(
            f"blob type {blob.type!r} is not retrievable as text"
        )

    async def fetch_bytes(self, blob: BlobLocator) -> tuple[bytes, str]:
        data = await self._file_bytes(blob.source_path)
        if blob.type == "PDF":
            sub = extract_pdf_pages_bytes(data, blob.file_start, blob.file_end)
            return sub, "application/pdf"
        if blob.type == "TEXT":
            text = data.decode("utf-8", errors="replace")
            return text[blob.file_start : blob.file_end].encode("utf-8"), "text/plain"
        raise UnsupportedBlobTypeError(
            f"blob type {blob.type!r} is not retrievable as bytes"
        )


async def build_blob_provider(
    source: FileSource,
    conn: PoolConnectionProxy,
    http: ClientSession,
    google_oauth_settings: GoogleOAuthSettings,
    user_id: int,
) -> BlobContentProvider:
    """Dispatch by source string. Today the only branch is GDRIVE; the
    Protocol seam exists so a future provider (Notion, S3, …) plugs in here
    without touching the agent or endpoint code.
    """
    if source == "GDRIVE":
        access_token = await access_token_for_user(
            conn, http, google_oauth_settings, user_id
        )
        return GDriveBlobProvider(http=http, access_token=access_token)
    raise ValueError(f"Unsupported blob source: {source!r}")
