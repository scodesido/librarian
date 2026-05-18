import asyncio
import logging

from aiohttp import ClientSession
from asyncpg import Pool
from pydantic_ai import Agent

from librarian.common.http.client import open_client_session
from librarian.db.connect import open_pool
from librarian.db.readiness import claim_next_unready_file
from librarian.service.abstract import RollingAbstract
from librarian.service.backoff import ExponentialBackoff
from librarian.service.blob_extractor.abstract import build_abstract_agent
from librarian.service.blob_extractor.embed import build_embedder
from librarian.service.blob_extractor.process import process_file
from librarian.service.embedder import Embedder
from librarian.service.settings import settings

logger = logging.getLogger(__name__)


async def worker_loop(
    pool: Pool,
    http: ClientSession,
    agent: Agent[None, RollingAbstract],
    embedder: Embedder,
) -> None:
    s = settings.blob_extractor
    backoff = ExponentialBackoff(
        initial_seconds=s.error_backoff_initial_seconds,
        max_seconds=s.error_backoff_max_seconds,
        multiplier=s.error_backoff_multiplier,
    )
    while True:
        try:
            did_work = await run_one_iteration(pool, http, agent, embedder)
            backoff.reset()
            if not did_work:
                await asyncio.sleep(s.poll_interval_seconds)
        except Exception:
            logger.exception("blob_extractor: iteration failed; backing off")
            await backoff.wait_and_advance()


# TODO: check that both the LLM and the embedder are reachable before starting the processing
# in order to e.g. avoid spending time on the LLM to then have the embedding fail
async def run_one_iteration(
    pool: Pool,
    http: ClientSession,
    agent: Agent[None, RollingAbstract],
    embedder: Embedder,
) -> bool:
    """One file's worth of work, atomically. Returns True iff a file was
    processed (so the caller can decide whether to sleep).

    The whole operation (claim, advisory lock, process, insert) runs inside
    a single transaction on a single pool connection. The advisory_xact_lock
    is redundant given the FOR UPDATE on the file row, but encodes the
    "this is one atomic unit per (user, file)" contract explicitly for any
    future reader.
    """
    s = settings.blob_extractor
    async with pool.acquire() as conn:
        async with conn.transaction():
            file = await claim_next_unready_file(conn)
            if file is None:
                return False
            await conn.execute(
                "SELECT pg_advisory_xact_lock($1, $2)",
                file.user_id,
                file.file_id,
            )
            logger.info(
                "blob_extractor: processing file %s (user %s, type %s)",
                file.file_id,
                file.user_id,
                file.type,
            )
            await process_file(
                file=file,
                conn=conn,
                http=http,
                agent=agent,
                embedder=embedder,
                settings=s,
                google_oauth_settings=settings.google_oauth,
            )
            logger.info("blob_extractor: file %s done", file.file_id)
    return True


async def run_worker() -> None:
    s = settings.blob_extractor
    agent = build_abstract_agent(s)
    embedder = build_embedder(s)
    logger.info("blob_extractor: starting %d worker(s)", s.concurrent_workers)
    async with (
        open_pool(settings.database) as pool,
        open_client_session(settings.http_client) as http,
    ):
        await asyncio.gather(
            *(
                worker_loop(pool, http, agent, embedder)
                for _ in range(s.concurrent_workers)
            )
        )
