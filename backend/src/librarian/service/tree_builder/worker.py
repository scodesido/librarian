import asyncio
import logging

from asyncpg import Pool

from librarian.db.connect import open_pool
from librarian.service.backoff import ExponentialBackoff
from librarian.service.events import record_failure
from librarian.service.settings import settings
from librarian.service.tree_builder.insert import insert_one_ready_blob
from librarian.service.tree_builder.pick import pick_user_with_work
from librarian.service.tree_builder.rebalance import split_one_overfull
from librarian.service.tree_builder.weights import backfill_one_weight

logger = logging.getLogger(__name__)


async def worker_loop(pool: Pool) -> None:
    s = settings.tree_builder
    backoff = ExponentialBackoff(
        initial_seconds=s.error_backoff_initial_seconds,
        max_seconds=s.error_backoff_max_seconds,
        multiplier=s.error_backoff_multiplier,
    )
    while True:
        try:
            did_work = await run_one_iteration(pool)
            backoff.reset()
            if not did_work:
                await asyncio.sleep(s.poll_interval_seconds)
        except Exception:
            logger.exception("tree_builder: iteration failed; backing off")
            await backoff.wait_and_advance()


async def run_one_iteration(pool: Pool) -> bool:
    """One unit of work: backfill one weight, OR split one over-K node, OR
    attach one ready blob. Priority order is exactly that — weights first
    so descents always see well-defined centroids, splits next so
    insertions land in a tree near its target shape, and insertions last.

    Returns True iff some work was done (so the caller can retry
    immediately instead of sleeping).
    """
    s = settings.tree_builder
    async with pool.acquire() as conn:
        async with conn.transaction():
            user_id = await pick_user_with_work(conn, s.max_children_per_node)
            if user_id is None:
                return False
            await conn.execute("SELECT pg_advisory_xact_lock($1)", user_id)

            try:
                if await backfill_one_weight(conn, user_id):
                    logger.info(
                        "tree_builder: backfilled one weight (user %s)", user_id
                    )
                    return True
                if await split_one_overfull(
                    conn, user_id, s.max_children_per_node, s.imbalance_alpha
                ):
                    logger.info(
                        "tree_builder: split one over-K node (user %s)", user_id
                    )
                    return True
                if await insert_one_ready_blob(conn, user_id, s.imbalance_alpha):
                    logger.info(
                        "tree_builder: attached one ready blob (user %s)", user_id
                    )
                    return True
            except Exception as exc:
                # Record on a fresh connection (the work txn is rolling
                # back), then re-raise to keep worker_loop's backoff.
                await record_failure(
                    pool, user_id, exc, "tree_builder", s.event_throttle_seconds
                )
                raise
    return False


async def run_worker() -> None:
    s = settings.tree_builder
    logger.info("tree_builder: starting %d worker(s)", s.concurrent_workers)
    async with open_pool(settings.database) as pool:
        await asyncio.gather(*(worker_loop(pool) for _ in range(s.concurrent_workers)))
