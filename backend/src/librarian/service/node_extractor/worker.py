import asyncio
import logging

from asyncpg import Pool

from librarian.db.connect import open_pool
from librarian.service.backoff import ExponentialBackoff
from librarian.service.node_extractor.abstract import NodeAgents, build_node_agents
from librarian.service.node_extractor.pick import pick_user_with_extractable_tree
from librarian.service.node_extractor.process import process_one_node
from librarian.service.settings import settings

logger = logging.getLogger(__name__)


async def worker_loop(pool: Pool, agents: NodeAgents) -> None:
    s = settings.node_extractor
    backoff = ExponentialBackoff(
        initial_seconds=s.error_backoff_initial_seconds,
        max_seconds=s.error_backoff_max_seconds,
        multiplier=s.error_backoff_multiplier,
    )
    while True:
        try:
            did_work = await run_one_iteration(pool, agents)
            backoff.reset()
            if not did_work:
                await asyncio.sleep(s.poll_interval_seconds)
        except Exception:
            logger.exception("node_extractor: iteration failed; backing off")
            await backoff.wait_and_advance()


async def run_one_iteration(pool: Pool, agents: NodeAgents) -> bool:
    """One node's abstract, atomically. Returns True iff a node was
    processed.

    The whole operation (gate check, claim, LLM call, INSERT) runs in a
    single transaction on one pool connection. The FOR UPDATE on the
    candidate node row is the claim; SKIP LOCKED lets parallel workers
    work on different nodes of the same (or other) users in parallel.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            user_id = await pick_user_with_extractable_tree(conn)
            if user_id is None:
                return False
            return await process_one_node(conn, agents, user_id)


async def run_worker() -> None:
    s = settings.node_extractor
    agents = build_node_agents(s)
    logger.info("node_extractor: starting %d worker(s)", s.concurrent_workers)
    async with open_pool(settings.database) as pool:
        await asyncio.gather(
            *(worker_loop(pool, agents) for _ in range(s.concurrent_workers))
        )
