import logging
from typing import Any

from asyncpg.pool import PoolConnectionProxy

from librarian.db.tables.data_node_abstracts import DataNodeAbstracts
from librarian.db.tables.user_token_usage import Operation
from librarian.db.tables.user_worker_events import EventCode
from librarian.service.events import record_event
from librarian.service.node_extractor.abstract import NodeAgents, extract_node_abstract
from librarian.service.usage import record_usage

logger = logging.getLogger(__name__)


class ProcessNodeError(Exception):
    pass


async def claim_next_extractable_node(
    conn: PoolConnectionProxy, user_id: int
) -> tuple[int, int, bool] | None:
    """Pick a node without a data_node_abstracts row whose children all
    have abstracts already (blob children are always "ready" because
    data_blobs.abstract is NOT NULL). Lock the row FOR UPDATE so a parallel
    worker skips it.

    Bottom-up ordering: lowest height first. Combined with parallel workers,
    one full height fills out before the next height becomes claimable.
    """
    record = await conn.fetchrow(
        """
        SELECT n.node_id, n.height, n.is_root
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
    return record["node_id"], record["height"], record["is_root"]


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
    agents: NodeAgents,
    user_id: int,
    leaf_model: str,
    internal_model: str,
    event_throttle_seconds: float,
) -> bool:
    """Claim, compute, insert. Returns True iff a node was processed.

    `agents` carries a per-height agent pair; the claimed node's height
    selects which one runs (haiku-class at height 0, sonnet-class above,
    by default — see NodeExtractorSettings). `leaf_model` / `internal_model`
    are the resolved "<provider>:<model>" strings used to build those
    agents; we use them verbatim for the usage ledger row so historical
    entries survive catalog edits.
    """
    claimed = await claim_next_extractable_node(conn, user_id)
    if claimed is None:
        return False
    node_id, height, is_root = claimed
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
    abstract, usage = await extract_node_abstract(agents.for_height(height), children)
    operation: Operation = (
        "node_extract_leaf" if height == 0 else "node_extract_internal"
    )
    model_used = leaf_model if height == 0 else internal_model
    await record_usage(conn, user_id, operation, model_used, usage)
    await DataNodeAbstracts(conn).insert(user_id, node_id, abstract.model_dump())
    if is_root:
        # The root abstract is the last piece that makes the library
        # queryable. Throttled: the root abstract is recomputed every time
        # the tree changes, so during an active build this would otherwise
        # fire on each pass — collapse the burst into one "ready" per window.
        await record_event(
            conn,
            user_id,
            EventCode.LIBRARY_ABSTRACTED,
            "node_extractor",
            detail="Your library is ready to query.",
            context={"node_id": node_id},
            throttle_window=event_throttle_seconds,
        )
    logger.info("node_extractor: node %s done", node_id)
    return True
