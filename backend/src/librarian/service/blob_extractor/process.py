from dataclasses import dataclass

from aiohttp import ClientSession
from asyncpg.pool import PoolConnectionProxy
from pydantic_ai import Agent, Embedder

from librarian.common.oauth.google.crypto import decrypt as decrypt_google_token
from librarian.common.oauth.google.tokens import refresh_access_token
from librarian.common.settings.google_oauth import GoogleOAuthSettings
from librarian.db.tables.auth_google import AuthGoogle
from librarian.db.tables.data_files import DataFilesModel
from librarian.service.blob_extractor.abstract import Abstract, extract_abstract
from librarian.service.blob_extractor.chunk import chunk_pdf, chunk_text
from librarian.service.blob_extractor.drive import download_file
from librarian.service.blob_extractor.embed import (
    compute_with_file_embeddings,
    embed_blobs,
)
from librarian.service.blob_extractor.insert import (
    PreparedBlob,
    insert_blobs_end_to_beginning,
)
from librarian.service.blob_extractor.pdf_text import extract_pdf_text
from librarian.service.blob_extractor.settings import BlobExtractorSettings


class ProcessFileError(Exception):
    pass


@dataclass
class ChunkRecord:
    file_start: int
    file_end: int
    llm_content: bytes | str
    llm_media_type: str
    raw_text: str


def chunks_for_pdf(pdf_bytes: bytes, pages_per_blob: int) -> list[ChunkRecord]:
    return [
        ChunkRecord(
            file_start=c.start_page,
            file_end=c.end_page,
            llm_content=c.pdf_bytes,
            llm_media_type="application/pdf",
            raw_text=extract_pdf_text(c.pdf_bytes),
        )
        for c in chunk_pdf(pdf_bytes, pages_per_blob)
    ]


def chunks_for_text(file_bytes: bytes, words_per_blob: int) -> list[ChunkRecord]:
    text = file_bytes.decode("utf-8", errors="replace")
    return [
        ChunkRecord(
            file_start=c.start_char,
            file_end=c.end_char,
            llm_content=c.text,
            llm_media_type="text/plain",
            raw_text=c.text,
        )
        for c in chunk_text(text, words_per_blob)
    ]


async def process_file(
    file: DataFilesModel,
    conn: PoolConnectionProxy,
    http: ClientSession,
    agent: Agent[None, Abstract],
    embedder: Embedder,
    settings: BlobExtractorSettings,
    google_oauth_settings: GoogleOAuthSettings,
) -> None:
    """Process one file end-to-end inside an already-open transaction on
    `conn`. The caller holds the file-row FOR UPDATE and the
    per-(user, file) advisory_xact_lock; on return the caller commits.

    Note: the LLM, Drive, and embedder calls all happen with the transaction
    open. The pool connection is pinned for the duration. This is by design
    (see docs/05.blob_extractor.md): atomicity of the file's blob set is
    worth the long lease on the connection.
    """
    auth = await AuthGoogle(conn).for_user(file.user_id)
    if auth is None:
        raise ProcessFileError(f"user {file.user_id} has no google auth")

    refresh_token = decrypt_google_token(
        google_oauth_settings.get_token_encryption_key, auth.refresh_token_enc
    )
    access_token = await refresh_access_token(
        http, google_oauth_settings, refresh_token
    )
    file_bytes = await download_file(http, access_token, file.path)

    if file.type == "PDF":
        chunks = chunks_for_pdf(file_bytes, settings.pages_per_blob)
    elif file.type == "TEXT":
        chunks = chunks_for_text(file_bytes, settings.words_per_blob)
    else:
        raise ProcessFileError(
            f"file {file.file_id} has unsupported type {file.type!r}; the "
            "claim query should have excluded it"
        )

    if not chunks:
        raise ProcessFileError(
            f"file {file.file_id} produced zero chunks; cannot create a "
            "final blob and so the file would never become ready"
        )

    abstracts: list[Abstract] = []
    previous_running: str | None = None
    for chunk in chunks:
        abstract = await extract_abstract(
            agent, chunk.llm_content, chunk.llm_media_type, previous_running
        )
        abstracts.append(abstract)
        previous_running = abstract.running_summary

    embedding_blobs = await embed_blobs(
        embedder,
        raw_texts=[c.raw_text for c in chunks],
        abstracts=abstracts,
    )
    embeddings_with_file = compute_with_file_embeddings(embedding_blobs)

    prepared = [
        PreparedBlob(
            file_blob_index=i,
            file_start=chunk.file_start,
            file_end=chunk.file_end,
            embedding_blob=eb,
            embedding_with_file=ewf,
            abstract=abstract.model_dump(),
        )
        for i, (chunk, abstract, eb, ewf) in enumerate(
            zip(chunks, abstracts, embedding_blobs, embeddings_with_file, strict=True)
        )
    ]
    await insert_blobs_end_to_beginning(conn, file.user_id, file.file_id, prepared)
