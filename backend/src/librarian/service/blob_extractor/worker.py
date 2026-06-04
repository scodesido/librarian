import asyncio
import logging

from aiohttp import ClientSession
from asyncpg import Pool

from librarian.common.http.client import open_client_session
from librarian.db.connect import open_pool
from librarian.db.tables.user_worker_events import EventCode
from librarian.service.backoff import ExponentialBackoff
from librarian.service.blob_extractor.abstract import build_main_agent
from librarian.service.blob_extractor.pick import (
    claim_unready_file,
    pick_user_with_unready_file,
)
from librarian.service.blob_extractor.process import ProcessOutcome, process_file
from librarian.service.blob_extractor.tagging import build_tag_agent
from librarian.service.credentials import (
    MissingTokenError,
    resolve_user_credentials,
)
from librarian.service.embedder import build_embedder
from librarian.service.events import record_event, record_failure
from librarian.service.settings import settings

logger = logging.getLogger(__name__)


async def worker_loop(pool: Pool, http: ClientSession) -> None:
    s = settings.blob_extractor
    backoff = ExponentialBackoff(
        initial_seconds=s.error_backoff_initial_seconds,
        max_seconds=s.error_backoff_max_seconds,
        multiplier=s.error_backoff_multiplier,
    )
    while True:
        try:
            did_work = await run_one_iteration(pool, http)
            backoff.reset()
            if not did_work:
                await asyncio.sleep(s.poll_interval_seconds)
        except Exception:
            logger.exception("blob_extractor: iteration failed; backing off")
            await backoff.wait_and_advance()


# TODO: check that both the LLM and the embedder are reachable before starting the processing
# in order to e.g. avoid spending time on the LLM to then have the embedding fail
async def run_one_iteration(pool: Pool, http: ClientSession) -> bool:
    """One file visit. Returns True iff a file was claimed (so the caller
    can decide whether to sleep), regardless of whether it was fully
    processed or invalidated.

    Picks a random user with unready files (rotation: spreads load, keeps a
    single broken-token user from monopolising the worker), resolves their
    credentials, claims one file via a session-level advisory lock, builds
    per-user agents/embedder, and runs `process_file` — which commits the
    blob set incrementally across many short transactions rather than one
    long one. The advisory lock (not a row `FOR UPDATE`, which would release
    between those short transactions) is what keeps a second worker off the
    file; it is released in the `finally` and, as a backstop, by the pool's
    reset when the connection is returned.

    A MissingTokenError raised by the credentials resolver is logged at info
    and treated as "no work done" (the user has a broken setup; don't burn
    the worker's exponential-backoff curve on it).
    """
    s = settings.blob_extractor
    async with pool.acquire() as conn:
        user_id = await pick_user_with_unready_file(conn)
        if user_id is None:
            return False
        try:
            creds = await resolve_user_credentials(
                conn,
                user_id,
                settings.model_catalog,
                settings.ollama,
                settings.user_tokens,
            )
        except MissingTokenError as exc:
            logger.info("blob_extractor: user %s skipped (%s)", user_id, exc)
            await record_event(
                conn,
                user_id,
                EventCode.MISSING_TOKEN,
                "blob_extractor",
                detail=str(exc),
                context={"slot": exc.slot, "model": exc.model},
                throttle_window=s.event_throttle_seconds,
            )
            return False
        file = await claim_unready_file(conn, user_id)
        if file is None:
            # The user's queue drained (or every unready file is locked by
            # another worker) between our pick and our claim. Treat as "no
            # work" so the caller sleeps.
            return False
        try:
            main_agent = build_main_agent(s, creds.blob_llm)
            tag_agent = build_tag_agent(s, creds.blob_llm)
            embedder = build_embedder(
                model=creds.embedding.model,
                api_token=creds.embedding.api_token,
                ollama_host=creds.embedding.ollama_host,
                dimensions=settings.embeddings.dimensions,
            )
            logger.info(
                "blob_extractor: processing file %s (user %s, type %s, "
                "llm=%s, embed=%s)",
                file.file_id,
                file.user_id,
                file.type,
                creds.blob_llm.model,
                creds.embedding.model,
            )
            try:
                outcome = await process_file(
                    file=file,
                    conn=conn,
                    http=http,
                    main_agent=main_agent,
                    tag_agent=tag_agent,
                    embedder=embedder,
                    blob_llm_model=creds.blob_llm.model,
                    embedding_model=creds.embedding.model,
                    settings=s,
                    embeddings_settings=settings.embeddings,
                    google_oauth_settings=settings.google_oauth,
                )
            except Exception as exc:
                # Committed blobs survive; record the failure on a fresh
                # connection (the work conn may be mid-rollback) and re-raise
                # so worker_loop's backoff is unchanged. The next visit
                # resumes from the last committed blob.
                await record_failure(
                    pool,
                    user_id,
                    exc,
                    "blob_extractor",
                    s.event_throttle_seconds,
                    context={"file_id": file.file_id},
                )
                raise
            if outcome is ProcessOutcome.PROCESSED:
                await record_event(
                    conn,
                    user_id,
                    EventCode.FILE_PROCESSED,
                    "blob_extractor",
                    detail=f"Processed {file.name or file.path}",
                    context={"file_id": file.file_id},
                )
                logger.info("blob_extractor: file %s done", file.file_id)
            else:
                logger.info(
                    "blob_extractor: file %s invalidated; will rebuild",
                    file.file_id,
                )
        finally:
            # Best-effort: release the session lock promptly. If the conn is
            # already broken the pool's reset releases it on return anyway, so
            # don't let an unlock failure mask the real processing error.
            try:
                await conn.execute(
                    "SELECT pg_advisory_unlock($1, $2)", user_id, file.file_id
                )
            except Exception:
                logger.warning(
                    "blob_extractor: advisory unlock failed for file %s",
                    file.file_id,
                )
    return True


async def run_worker() -> None:
    s = settings.blob_extractor
    logger.info("blob_extractor: starting %d worker(s)", s.concurrent_workers)
    async with (
        open_pool(settings.database) as pool,
        open_client_session(settings.http_client) as http,
    ):
        await asyncio.gather(
            *(worker_loop(pool, http) for _ in range(s.concurrent_workers))
        )
