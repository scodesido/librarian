import asyncio
import logging

from asyncpg import Pool

from librarian.db.connect import open_pool
from librarian.db.tables.user_worker_events import EventCode
from librarian.service.backoff import ExponentialBackoff
from librarian.service.credentials import (
    MissingTokenError,
    resolve_user_credentials,
)
from librarian.service.events import record_event, record_failure
from librarian.service.node_extractor.abstract import (
    NodeAgents,
    build_node_abstract_agent,
)
from librarian.service.node_extractor.pick import pick_user_with_extractable_tree
from librarian.service.node_extractor.process import process_one_node
from librarian.service.settings import settings

logger = logging.getLogger(__name__)


async def worker_loop(pool: Pool) -> None:
    s = settings.node_extractor
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
            logger.exception("node_extractor: iteration failed; backing off")
            await backoff.wait_and_advance()


async def run_one_iteration(pool: Pool) -> bool:
    """One node's abstract, atomically. Returns True iff a node was
    processed.

    Pick a random eligible user (rotation: doesn't get stuck on one user
    with broken credentials), resolve their credentials, build both
    height-side agents for this iteration, then claim+process one node.
    Per-iteration agent construction is cheap (cents-of-cents) and gets
    the user's latest model pick automatically on the next iteration.

    The whole sequence runs in a single transaction on one pool
    connection. The FOR UPDATE on the candidate node row is the claim;
    SKIP LOCKED lets parallel workers work on different nodes of the
    same (or other) users in parallel.
    """
    s = settings.node_extractor
    async with pool.acquire() as conn:
        async with conn.transaction():
            user_id = await pick_user_with_extractable_tree(conn)
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
                logger.info("node_extractor: user %s skipped (%s)", user_id, exc)
                await record_event(
                    conn,
                    user_id,
                    EventCode.MISSING_TOKEN,
                    "node_extractor",
                    detail=str(exc),
                    context={"slot": exc.slot, "model": exc.model},
                    throttle_window=s.event_throttle_seconds,
                )
                return False
            agents = NodeAgents(
                leaf=build_node_abstract_agent(s, creds.node_llm_leaf),
                internal=build_node_abstract_agent(s, creds.node_llm_internal),
            )
            try:
                return await process_one_node(
                    conn,
                    agents,
                    user_id,
                    leaf_model=creds.node_llm_leaf.model,
                    internal_model=creds.node_llm_internal.model,
                    event_throttle_seconds=s.event_throttle_seconds,
                )
            except Exception as exc:
                # Record on a fresh connection (the work txn is rolling
                # back), then re-raise to keep worker_loop's backoff.
                await record_failure(
                    pool, user_id, exc, "node_extractor", s.event_throttle_seconds
                )
                raise


async def run_worker() -> None:
    s = settings.node_extractor
    logger.info("node_extractor: starting %d worker(s)", s.concurrent_workers)
    async with open_pool(settings.database) as pool:
        await asyncio.gather(*(worker_loop(pool) for _ in range(s.concurrent_workers)))
