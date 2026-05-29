import logging
from dataclasses import dataclass

from aiohttp import ClientSession
from asyncpg.pool import PoolConnectionProxy
from pydantic_ai import Agent, BinaryContent

from librarian.common.oauth.google.access import (
    NoGoogleAuthError,
    access_token_for_user,
)
from librarian.common.settings.embeddings import EmbeddingsSettings
from librarian.common.settings.google_oauth import GoogleOAuthSettings
from librarian.db.tables.data_files import DataFilesModel
from librarian.service.abstract import BlobTags, RollingAbstract, RollingAbstractCore
from librarian.service.blob_extractor.abstract import extract_main
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
from librarian.service.blob_extractor.pdf_images import pdf_pages_to_pngs
from librarian.service.blob_extractor.pdf_text import extract_pdf_text
from librarian.service.blob_extractor.settings import BlobExtractorSettings
from librarian.service.blob_extractor.tagging import classify_tags
from librarian.service.embedder import Embedder

logger = logging.getLogger(__name__)


class ProcessFileError(Exception):
    pass


@dataclass
class ChunkRecord:
    file_start: int
    file_end: int
    llm_content: bytes | str
    llm_media_type: str
    # PNG bytes of the chunk's pages, in page order. Populated only for
    # PDF chunks when llm_pdf_mode == "images"; empty list otherwise.
    llm_images: list[bytes]
    raw_text: str


def chunks_for_pdf(
    pdf_bytes: bytes,
    pages_per_blob: int,
    render_images: bool,
    image_dpi: int,
) -> list[ChunkRecord]:
    sub_pdfs = chunk_pdf(pdf_bytes, pages_per_blob)
    # Render the whole PDF once when we need images, then slice by the
    # 0-based half-open [start_page, end_page) range of each chunk.
    page_pngs = pdf_pages_to_pngs(pdf_bytes, image_dpi) if render_images else []
    return [
        ChunkRecord(
            file_start=c.start_page,
            file_end=c.end_page,
            llm_content=c.pdf_bytes,
            llm_media_type="application/pdf",
            llm_images=page_pngs[c.start_page : c.end_page] if render_images else [],
            raw_text=extract_pdf_text(c.pdf_bytes),
        )
        for c in sub_pdfs
    ]


def chunks_for_text(file_bytes: bytes, words_per_blob: int) -> list[ChunkRecord]:
    text = file_bytes.decode("utf-8", errors="replace")
    return [
        ChunkRecord(
            file_start=c.start_char,
            file_end=c.end_char,
            llm_content=c.text,
            llm_media_type="text/plain",
            llm_images=[],
            raw_text=c.text,
        )
        for c in chunk_text(text, words_per_blob)
    ]


def build_llm_content_parts(chunk: ChunkRecord, mode: str) -> list[str | BinaryContent]:
    """Compose the per-chunk content sent to the LLM, choosing between
    extracted text, raw PDF bytes, or page images based on the configured
    PDF mode. Text-typed chunks always go as text; the mode only affects
    PDFs.
    """
    is_pdf = isinstance(chunk.llm_content, bytes)
    if not is_pdf or mode == "text":
        return [f"Blob content:\n\n{chunk.raw_text}"]
    if mode == "binary":
        assert isinstance(chunk.llm_content, bytes)
        return [BinaryContent(data=chunk.llm_content, media_type="application/pdf")]
    if mode == "images":
        if not chunk.llm_images:
            raise ProcessFileError(
                "llm_pdf_mode is 'images' but the chunk has no rendered "
                "pages; chunks_for_pdf must be called with render_images=True"
            )
        return [
            BinaryContent(data=png, media_type="image/png") for png in chunk.llm_images
        ]
    raise ProcessFileError(f"Unknown llm_pdf_mode: {mode!r}")


async def process_file(
    file: DataFilesModel,
    conn: PoolConnectionProxy,
    http: ClientSession,
    main_agent: Agent[None, RollingAbstractCore],
    tag_agent: Agent[None, BlobTags],
    embedder: Embedder,
    settings: BlobExtractorSettings,
    embeddings_settings: EmbeddingsSettings,
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
    try:
        access_token = await access_token_for_user(
            conn, http, google_oauth_settings, file.user_id
        )
    except NoGoogleAuthError as exc:
        raise ProcessFileError(str(exc)) from exc
    file_bytes = await download_file(http, access_token, file.path)

    if file.type == "PDF":
        chunks = chunks_for_pdf(
            file_bytes,
            settings.pages_per_blob,
            render_images=settings.llm_pdf_mode == "images",
            image_dpi=settings.pdf_image_dpi,
        )
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

    abstracts: list[RollingAbstract] = []
    previous_running: str | None = None
    n_chunks = len(chunks)
    for i, chunk in enumerate(chunks):
        content_parts = build_llm_content_parts(chunk, settings.llm_pdf_mode)
        core = await extract_main(main_agent, content_parts, previous_running)
        tags = await classify_tags(tag_agent, core)
        # Assemble the final RollingAbstract. model_validate re-runs the
        # ≥1-per-facet validator from Abstract; the Literal + min_length
        # constraints on RollingAbstract's tag fields catch any drift
        # that slipped past the tag agent (which has the same
        # constraints on BlobTags).
        abstract = RollingAbstract.model_validate(
            {
                **core.model_dump(),
                "content_tags": tags.content_tags,
                "format_tags": tags.format_tags,
            }
        )
        abstracts.append(abstract)
        previous_running = abstract.running_summary
        logger.info(
            "blob_extractor: file %s blob %d/%d abstracted: topics=%s tags=%s/%s",
            file.file_id,
            i + 1,
            n_chunks,
            abstract.topics,
            abstract.content_tags,
            abstract.format_tags,
        )

    embedding_blobs = await embed_blobs(
        http,
        embedder,
        raw_texts=[c.raw_text for c in chunks],
        abstracts=abstracts,
        chunk_chars=embeddings_settings.chunk_chars,
        chunk_chars_max=embeddings_settings.chunk_chars_max,
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
