import logging
from typing import Any

from asyncpg.pool import PoolConnectionProxy
from pydantic_ai import Agent

from librarian.db.tables.data_node_abstracts import DataNodeAbstracts
from librarian.service.abstract import AbstractCore
from librarian.service.node_extractor.abstract import extract_node_abstract

logger = logging.getLogger(__name__)


class ProcessNodeError(Exception):
    pass


async def claim_next_extractable_node(
    conn: PoolConnectionProxy, user_id: int
) -> tuple[int, int] | None:
    """Pick a node without a data_node_abstracts row whose children all
    have abstracts already (blob children are always "ready" because
    data_blobs.abstract is NOT NULL). Lock the row FOR UPDATE so a parallel
    worker skips it.

    Bottom-up ordering: lowest height first. Combined with parallel workers,
    one full height fills out before the next height becomes claimable.
    """
    record = await conn.fetchrow(
        """
        SELECT n.node_id, n.height
        FROM data_nodes n
        WHERE n.user_id = $1
          AND NOT EXISTS (
              SELECT 1 FROM data_node_abstracts a WHERE a.node_id = n.node_id
          )
          AND NOT EXISTS (
              SELECT 1 FROM data_node_edges e
              WHERE e.parent_node_id = n.node_id
                AND NOT EXISTS (
                    SELECT 1 FROM data_node_abstracts a2
                    WHERE a2.node_id = e.child_node_id
                )
          )
          AND (
              EXISTS (
                  SELECT 1 FROM data_node_edges e
                  WHERE e.parent_node_id = n.node_id
              )
              OR EXISTS (
                  SELECT 1 FROM data_blob_edges e
                  WHERE e.parent_node_id = n.node_id
              )
          )
        ORDER BY n.height
        LIMIT 1
        FOR UPDATE SKIP LOCKED
        """,
        user_id,
    )
    if record is None:
        return None
    return record["node_id"], record["height"]


async def fetch_children_abstracts(
    conn: PoolConnectionProxy, user_id: int, node_id: int, height: int
) -> list[dict[str, Any]]:
    """Children's Abstracts as a list of JSON dicts. height=0 nodes have
    blob children (data_blobs.abstract); height>0 nodes have node children
    (data_node_abstracts.abstract). The height invariant on the edge
    tables prevents a node from having both.
    """
    if height == 0:
        rows = await conn.fetch(
            "SELECT b.abstract FROM data_blob_edges e "
            "JOIN data_blobs b ON b.blob_id = e.child_blob_id "
            "WHERE e.user_id = $1 AND e.parent_node_id = $2",
            user_id,
            node_id,
        )
    else:
        rows = await conn.fetch(
            "SELECT a.abstract FROM data_node_edges e "
            "JOIN data_node_abstracts a ON a.node_id = e.child_node_id "
            "WHERE e.user_id = $1 AND e.parent_node_id = $2",
            user_id,
            node_id,
        )
    return [row["abstract"] for row in rows]


async def process_one_node(
    conn: PoolConnectionProxy,
    agent: Agent[None, AbstractCore],
    user_id: int,
) -> bool:
    """Claim, compute, insert. Returns True iff a node was processed."""
    claimed = await claim_next_extractable_node(conn, user_id)
    if claimed is None:
        return False
    node_id, height = claimed
    children = await fetch_children_abstracts(conn, user_id, node_id, height)
    if not children:
        raise ProcessNodeError(
            f"node {node_id} has no children at extraction time; the candidate "
            "query should have excluded it"
        )
    logger.info(
        "node_extractor: extracting node %s (user %s, height %s, %d children)",
        node_id,
        user_id,
        height,
        len(children),
    )
    abstract = await extract_node_abstract(agent, children)
    await DataNodeAbstracts(conn).insert(user_id, node_id, abstract.model_dump())
    logger.info("node_extractor: node %s done", node_id)
    return True
