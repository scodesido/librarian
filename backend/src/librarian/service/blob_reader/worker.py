import asyncio
import logging
from datetime import timedelta

from aiohttp import ClientSession
from asyncpg import Pool
from pydantic_ai import Agent, Embedder

from librarian.db.connect import open_pool
from librarian.db.tables.data_files import DataFiles
from librarian.http.client import open_client_session
from librarian.service.blob_reader.abstract import Abstract, build_abstract_agent
from librarian.service.blob_reader.embed import build_embedder
from librarian.service.blob_reader.process import process_file
from librarian.service.settings import settings

logger = logging.getLogger(__name__)


async def worker_loop(
    pool: Pool,
    http: ClientSession,
    agent: Agent[None, Abstract],
    embedder: Embedder,
) -> None:
    s = settings.blob_reader
    while True:
        async with pool.acquire() as conn:
            file = await DataFiles(conn).claim_next_pending()
        if file is None:
            await asyncio.sleep(s.poll_interval_seconds)
            continue
        logger.info("blob_reader: processing file %s (%s)", file.file_id, file.type)
        try:
            await process_file(
                file=file,
                pool=pool,
                http=http,
                agent=agent,
                embedder=embedder,
                settings=s,
                google_oauth_settings=settings.google_oauth,
            )
            logger.info("blob_reader: file %s done", file.file_id)
        except Exception:
            logger.exception("blob_reader: file %s failed", file.file_id)
            async with pool.acquire() as conn:
                await DataFiles(conn).mark_failed(file.file_id)


async def stale_claim_sweeper(pool: Pool) -> None:
    s = settings.blob_reader
    timeout = timedelta(seconds=s.claim_timeout_seconds)
    sweep_interval = max(60.0, s.claim_timeout_seconds / 4)
    while True:
        async with pool.acquire() as conn:
            n = await DataFiles(conn).sweep_stale_processing(timeout)
        if n > 0:
            logger.warning("blob_reader: swept %d stale claims back to PENDING", n)
        await asyncio.sleep(sweep_interval)


async def run_worker() -> None:
    s = settings.blob_reader
    agent = build_abstract_agent(s)
    embedder = build_embedder(s)
    async with (
        open_pool(settings.database) as pool,
        open_client_session(settings.http_client) as http,
    ):
        tasks = [
            asyncio.create_task(worker_loop(pool, http, agent, embedder))
            for _ in range(s.concurrent_workers)
        ]
        tasks.append(asyncio.create_task(stale_claim_sweeper(pool)))
        await asyncio.gather(*tasks)
