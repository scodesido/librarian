import hashlib
import logging
from dataclasses import dataclass
from enum import Enum

from aiohttp import ClientSession
from asyncpg.pool import PoolConnectionProxy
from pydantic_ai import Agent, BinaryContent

from librarian.common.oauth.google.access import (
    NoGoogleAuthError,
    access_token_for_user,
)
from librarian.common.settings.embeddings import EmbeddingsSettings
from librarian.common.settings.google_oauth import GoogleOAuthSettings
from librarian.db.tables.data_blob_file_embeddings import DataBlobFileEmbeddings
from librarian.db.tables.data_blobs import DataBlobs, DataBlobsModel
from librarian.db.tables.data_file_manifests import DataFileManifests
from librarian.db.tables.data_files import DataFilesModel
from librarian.service.abstract import BlobTags, RollingAbstract, RollingAbstractCore
from librarian.service.blob_extractor.abstract import extract_main
from librarian.service.blob_extractor.chunk import chunk_pdf, chunk_text
from librarian.service.blob_extractor.drive import download_file
from librarian.service.blob_extractor.embed import (
    compute_with_file_embeddings,
    embed_blobs,
)
from librarian.service.blob_extractor.pdf_images import pdf_pages_to_pngs
from librarian.service.blob_extractor.pdf_text import extract_pdf_text
from librarian.service.blob_extractor.settings import BlobExtractorSettings
from librarian.service.blob_extractor.tagging import classify_tags
from librarian.service.embedder import Embedder
from librarian.service.usage import TokenUsage, record_usage

logger = logging.getLogger(__name__)


class ProcessFileError(Exception):
    pass


class ProcessOutcome(Enum):
    # The file is now fully processed (manifest + all blobs + all file
    # embeddings present); it reads as ready.
    PROCESSED = "processed"
    # The file's content drifted from the manifest; its blobs were dropped
    # and the next visit rebuilds from a clean slate.
    INVALIDATED = "invalidated"


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


@dataclass
class ManifestMeta:
    expected_blob_count: int
    page_count: int | None
    char_count: int | None
    byte_size: int
    content_hash: str


def chunks_and_meta(
    file: DataFilesModel, file_bytes: bytes, settings: BlobExtractorSettings
) -> tuple[list[ChunkRecord], ManifestMeta]:
    """Deterministically chunk the file and derive its manifest metadata.
    Pure function of the bytes: the same input always yields the same
    chunks and the same expected_blob_count, which is what lets a later
    visit detect content drift by recomputing and comparing.
    """
    if file.type == "PDF":
        chunks = chunks_for_pdf(
            file_bytes,
            settings.pages_per_blob,
            render_images=settings.llm_pdf_mode == "images",
            image_dpi=settings.pdf_image_dpi,
        )
        page_count = chunks[-1].file_end if chunks else 0
        char_count = None
    elif file.type == "TEXT":
        chunks = chunks_for_text(file_bytes, settings.words_per_blob)
        page_count = None
        char_count = len(file_bytes.decode("utf-8", errors="replace"))
    else:
        raise ProcessFileError(
            f"file {file.file_id} has unsupported type {file.type!r}; the "
            "claim query should have excluded it"
        )
    if not chunks:
        raise ProcessFileError(
            f"file {file.file_id} produced zero chunks; it would never become "
            "ready (expected_blob_count must be >= 1)"
        )
    meta = ManifestMeta(
        expected_blob_count=len(chunks),
        page_count=page_count,
        char_count=char_count,
        byte_size=len(file_bytes),
        content_hash=hashlib.sha256(file_bytes).hexdigest(),
    )
    return chunks, meta


def content_drifted(
    existing: list[DataBlobsModel],
    chunks: list[ChunkRecord],
    expected_blob_count: int,
) -> bool:
    """The file changed underneath us if the recomputed chunk count no
    longer matches the manifest, or any already-stored blob's range no
    longer matches its recomputed chunk. Either invalidates the whole set.
    """
    if len(chunks) != expected_blob_count:
        return True
    return any(
        blob.file_start != chunks[i].file_start or blob.file_end != chunks[i].file_end
        for i, blob in enumerate(existing)
    )


async def abstract_chunk(
    chunk: ChunkRecord,
    previous_running: str | None,
    main_agent: Agent[None, RollingAbstractCore],
    tag_agent: Agent[None, BlobTags],
    mode: str,
) -> tuple[RollingAbstract, TokenUsage, TokenUsage]:
    """Run the two LLM agents for one chunk and assemble its
    RollingAbstract. No DB transaction is held during these network calls.
    Returns the abstract plus the main- and tag-agent usage.
    """
    content_parts = build_llm_content_parts(chunk, mode)
    core, main_usage = await extract_main(main_agent, content_parts, previous_running)
    tags, tag_usage = await classify_tags(tag_agent, core)
    # model_validate re-runs the ≥1-per-facet validator from Abstract; the
    # Literal + min_length constraints on RollingAbstract's tag fields catch
    # any drift that slipped past the tag agent.
    abstract = RollingAbstract.model_validate(
        {
            **core.model_dump(),
            "content_tags": tags.content_tags,
            "format_tags": tags.format_tags,
        }
    )
    return abstract, main_usage, tag_usage


async def process_file(
    file: DataFilesModel,
    conn: PoolConnectionProxy,
    http: ClientSession,
    main_agent: Agent[None, RollingAbstractCore],
    tag_agent: Agent[None, BlobTags],
    embedder: Embedder,
    blob_llm_model: str,
    embedding_model: str,
    settings: BlobExtractorSettings,
    embeddings_settings: EmbeddingsSettings,
    google_oauth_settings: GoogleOAuthSettings,
) -> ProcessOutcome:
    """Process one file incrementally. The caller holds a session-level
    advisory lock on (user_id, file_id) for the duration but does NOT hold
    an open transaction: this function opens its own short transaction per
    blob (and one for the manifest, one for the file-embedding batch), so a
    crash loses at most the blob in flight.

    The flow (see docs/19.per_blob_processing.md):
      1. Download + deterministically chunk the file.
      2. Write the manifest (first visit) or load it and check for content
         drift; on drift, drop the manifest (cascading blobs) and bail —
         the next visit rebuilds clean.
      3. Abstract + embed each not-yet-present chunk, committing one blob
         per short transaction; resume from the highest index already
         present, seeding the running_summary from the last stored blob.
      4. Once every blob exists, compute the file-relative embeddings (pure
         arithmetic, no network) and insert them as one atomic batch.

    `blob_llm_model` / `embedding_model` are the resolved "<provider>:<model>"
    strings, recorded verbatim on the usage ledger rows.
    """
    manifests = DataFileManifests(conn)
    blobs = DataBlobs(conn)
    file_embeds = DataBlobFileEmbeddings(conn)

    try:
        access_token = await access_token_for_user(
            conn, http, google_oauth_settings, file.user_id
        )
    except NoGoogleAuthError as exc:
        raise ProcessFileError(str(exc)) from exc
    file_bytes = await download_file(http, access_token, file.path)
    chunks, meta = chunks_and_meta(file, file_bytes, settings)

    manifest = await manifests.fetch(file.file_id)
    if manifest is None:
        async with conn.transaction():
            await manifests.insert(
                user_id=file.user_id,
                file_id=file.file_id,
                expected_blob_count=meta.expected_blob_count,
                page_count=meta.page_count,
                char_count=meta.char_count,
                byte_size=meta.byte_size,
                content_hash=meta.content_hash,
            )
        existing: list[DataBlobsModel] = []
        expected = meta.expected_blob_count
    else:
        expected = manifest.expected_blob_count
        existing = await blobs.fetch_for_file(file.file_id)
        if content_drifted(existing, chunks, expected):
            logger.info(
                "blob_extractor: file %s content drifted (expected %d blobs, "
                "now %d chunks); invalidating",
                file.file_id,
                expected,
                len(chunks),
            )
            async with conn.transaction():
                await manifests.delete(file.file_id)
            return ProcessOutcome.INVALIDATED

    previous_running: str | None = (
        existing[-1].abstract.get("running_summary") if existing else None
    )
    for i in range(len(existing), expected):
        chunk = chunks[i]
        abstract, main_usage, tag_usage = await abstract_chunk(
            chunk, previous_running, main_agent, tag_agent, settings.llm_pdf_mode
        )
        embedding_blobs, embed_input_tokens = await embed_blobs(
            http,
            embedder,
            raw_texts=[chunk.raw_text],
            abstracts=[abstract],
            chunk_chars=embeddings_settings.chunk_chars,
            chunk_chars_max=embeddings_settings.chunk_chars_max,
        )
        async with conn.transaction():
            await blobs.insert_one(
                user_id=file.user_id,
                file_id=file.file_id,
                file_blob_index=i,
                file_start=chunk.file_start,
                file_end=chunk.file_end,
                embedding_blob=embedding_blobs[0],
                abstract=abstract.model_dump(),
            )
            await record_usage(
                conn, file.user_id, "blob_extract", blob_llm_model, main_usage
            )
            await record_usage(
                conn, file.user_id, "blob_tag", blob_llm_model, tag_usage
            )
            # Embedders have no "output tokens" notion; output_tokens=0.
            await record_usage(
                conn,
                file.user_id,
                "embed_blob",
                embedding_model,
                TokenUsage(input_tokens=embed_input_tokens, output_tokens=0),
            )
        previous_running = abstract.running_summary
        logger.info(
            "blob_extractor: file %s blob %d/%d abstracted: topics=%s tags=%s/%s",
            file.file_id,
            i + 1,
            expected,
            abstract.topics,
            abstract.content_tags,
            abstract.format_tags,
        )

    # File-relative embeddings: pure arithmetic over the stored embedding_blob
    # vectors, inserted as one atomic batch. Existence of these rows is what
    # marks the file ready, so this is the last step.
    if not await file_embeds.exists_for_file(file.file_id):
        rows = await blobs.fetch_embedding_blobs(file.file_id)
        with_file = compute_with_file_embeddings([eb for _, eb in rows])
        items = [
            (blob_id, ewf) for (blob_id, _), ewf in zip(rows, with_file, strict=True)
        ]
        async with conn.transaction():
            await file_embeds.insert_many(file.user_id, file.file_id, items)

    return ProcessOutcome.PROCESSED
