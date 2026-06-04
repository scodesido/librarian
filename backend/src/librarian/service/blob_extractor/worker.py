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
    claim_next_unready_file_for_user,
    pick_user_with_unready_file,
)
from librarian.service.blob_extractor.process import process_file
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
    """One file's worth of work, atomically. Returns True iff a file was
    processed (so the caller can decide whether to sleep).

    Picks a random user with unready files (rotation: spreads load,
    keeps a single broken-token user from monopolising the worker),
    resolves their credentials, claims one file, builds per-user
    agents/embedder, and runs `process_file`. The whole sequence runs
    inside one transaction on one pool connection — the
    `advisory_xact_lock` is redundant given the FOR UPDATE on the file
    row but encodes the "this is one atomic unit per (user, file)"
    contract explicitly for any future reader.

    A MissingTokenError raised by the credentials resolver is logged at
    info and treated as "no work done" (the user has a broken setup;
    don't burn the worker's exponential-backoff curve on it). The next
    iteration's random pick is just as likely to land on someone with
    valid creds.
    """
    s = settings.blob_extractor
    async with pool.acquire() as conn:
        async with conn.transaction():
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
            file = await claim_next_unready_file_for_user(conn, user_id)
            if file is None:
                # Race: another worker grabbed the only remaining file
                # between our pick and our claim. Treat as "no work" so
                # the caller sleeps.
                return False
            await conn.execute(
                "SELECT pg_advisory_xact_lock($1, $2)",
                file.user_id,
                file.file_id,
            )
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
                await process_file(
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
                # The work transaction is unwinding, so record on a fresh
                # connection (record_failure) — the event must outlive the
                # rollback. Re-raise so worker_loop's backoff is unchanged.
                await record_failure(
                    pool,
                    user_id,
                    exc,
                    "blob_extractor",
                    s.event_throttle_seconds,
                    context={"file_id": file.file_id},
                )
                raise
            await record_event(
                conn,
                user_id,
                EventCode.FILE_PROCESSED,
                "blob_extractor",
                detail=f"Processed {file.name or file.path}",
                context={"file_id": file.file_id},
            )
            logger.info("blob_extractor: file %s done", file.file_id)
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
