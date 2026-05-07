from dataclasses import dataclass

from aiohttp import ClientSession
from asyncpg import Pool
from pydantic_ai import Agent, Embedder

from librarian.db.tables.auth_google import AuthGoogle
from librarian.db.tables.data_blobs import DataBlobs
from librarian.db.tables.data_files import DataFiles, DataFilesModel
from librarian.db.tables.node_embeddings import NodeEmbeddings
from librarian.db.tables.tree_nodes import TreeNodes
from librarian.oauth.google.crypto import decrypt as decrypt_google_token
from librarian.oauth.google.tokens import refresh_access_token
from librarian.service.blob_reader.abstract import Abstract, extract_abstract
from librarian.service.blob_reader.chunking import chunk_pdf, chunk_text
from librarian.service.blob_reader.drive import download_file
from librarian.service.blob_reader.embed import embed_abstracts
from librarian.service.blob_reader.settings import BlobReaderSettings
from librarian.settings.google_oauth import GoogleOAuthSettings


class ProcessFileError(Exception):
    pass


@dataclass
class Chunk:
    start: int
    end: int
    content: bytes | str
    media_type: str


def chunks_for_pdf(pdf_bytes: bytes, pages_per_blob: int) -> list[Chunk]:
    return [
        Chunk(b.start_page, b.end_page, b.pdf_bytes, "application/pdf")
        for b in chunk_pdf(pdf_bytes, pages_per_blob)
    ]


def chunks_for_text(file_bytes: bytes, words_per_blob: int) -> list[Chunk]:
    text = file_bytes.decode("utf-8", errors="replace")
    return [
        Chunk(b.start_char, b.end_char, b.text, "text/plain")
        for b in chunk_text(text, words_per_blob)
    ]


async def process_file(
    file: DataFilesModel,
    pool: Pool,
    http: ClientSession,
    agent: Agent[None, Abstract],
    embedder: Embedder,
    settings: BlobReaderSettings,
    google_oauth_settings: GoogleOAuthSettings,
) -> None:
    if file.type == "OTHER":
        async with pool.acquire() as conn:
            await DataFiles(conn).mark_ready(file.file_id)
        return

    async with pool.acquire() as conn:
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
    else:  # TEXT
        chunks = chunks_for_text(file_bytes, settings.words_per_blob)

    if not chunks:
        async with pool.acquire() as conn:
            await DataFiles(conn).mark_ready(file.file_id)
        return

    abstracts: list[Abstract] = []
    previous_running: str | None = None
    for chunk in chunks:
        abstract = await extract_abstract(
            agent, chunk.content, chunk.media_type, previous_running
        )
        abstracts.append(abstract)
        previous_running = abstract.running_summary

    per_blob_embeddings = await embed_abstracts(
        embedder, abstracts, settings.embedded_fields
    )

    async with pool.acquire() as conn, conn.transaction():
        for chunk, abstract, embeddings in zip(
            chunks, abstracts, per_blob_embeddings, strict=True
        ):
            blob_id = await DataBlobs(conn).create(file.file_id, chunk.start, chunk.end)
            node_id = await TreeNodes(conn).create_leaf(
                file.user_id, blob_id, abstract.model_dump()
            )
            await NodeEmbeddings(conn).bulk_insert(
                node_id, settings.embedding_model, embeddings
            )
        await DataFiles(conn).mark_ready(file.file_id)
