from typing import Annotated, Any, Literal, Union

from asyncpg.pool import PoolConnectionProxy
from pydantic import BaseModel, Field

# Prefixed string refs used at the LLM-facing tool boundary so a node_id and
# a blob_id of the same integer value can never be confused. `node_id` and
# `blob_id` int fields are preserved on the view models — the FE renders
# from them; the agent passes `ref` to the tools verbatim.
NODE_REF_PREFIX = "n:"
BLOB_REF_PREFIX = "b:"


def node_ref(node_id: int) -> str:
    return f"{NODE_REF_PREFIX}{node_id}"


def blob_ref(blob_id: int) -> str:
    return f"{BLOB_REF_PREFIX}{blob_id}"


class InvalidNodeRefError(Exception):
    """Raised by parse_node_ref when given a string that isn't a valid
    `n:NNN` ref — most commonly because the agent passed a `b:` (blob)
    ref to a tool that expects nodes.
    """


class InvalidBlobRefError(Exception):
    """Symmetric to InvalidNodeRefError: parse_blob_ref got a non-`b:` ref."""


def parse_node_ref(ref: str) -> int:
    if not ref.startswith(NODE_REF_PREFIX):
        raise InvalidNodeRefError(
            f"expected a node ref like 'n:NNN', got {ref!r}. "
            f"If this is a blob ref (starts with 'b:'), it belongs to "
            f"`fetch_blob_contents`, not `expand_nodes`."
        )
    try:
        return int(ref[len(NODE_REF_PREFIX) :])
    except ValueError as exc:
        raise InvalidNodeRefError(f"node ref {ref!r} has a non-integer body") from exc


def parse_blob_ref(ref: str) -> int:
    if not ref.startswith(BLOB_REF_PREFIX):
        raise InvalidBlobRefError(
            f"expected a blob ref like 'b:NNN', got {ref!r}. "
            f"If this is a node ref (starts with 'n:'), it belongs to "
            f"`expand_nodes`, not `fetch_blob_contents`."
        )
    try:
        return int(ref[len(BLOB_REF_PREFIX) :])
    except ValueError as exc:
        raise InvalidBlobRefError(f"blob ref {ref!r} has a non-integer body") from exc


class NodeChildView(BaseModel):
    kind: Literal["node"] = "node"
    ref: str
    node_id: int
    height: int
    abstract: dict[str, Any] | None
    blob_count: int | None


class BlobChildView(BaseModel):
    kind: Literal["blob"] = "blob"
    ref: str
    blob_id: int
    abstract: dict[str, Any]
    file_id: int
    file_blob_index: int
    file_start: int
    file_end: int


ChildView = Annotated[Union[NodeChildView, BlobChildView], Field(discriminator="kind")]


class NodeRow(BaseModel):
    node_id: int
    is_root: bool
    height: int


async def fetch_node_row(
    conn: PoolConnectionProxy, user_id: int, node_id: int | None
) -> NodeRow | None:
    """Either the named node (if `node_id` is set) or the user's root."""
    if node_id is None:
        record = await conn.fetchrow(
            "SELECT node_id, is_root, height FROM data_nodes "
            "WHERE user_id = $1 AND is_root",
            user_id,
        )
    else:
        record = await conn.fetchrow(
            "SELECT node_id, is_root, height FROM data_nodes "
            "WHERE user_id = $1 AND node_id = $2",
            user_id,
            node_id,
        )
    if record is None:
        return None
    return NodeRow(
        node_id=record["node_id"],
        is_root=record["is_root"],
        height=record["height"],
    )


async def fetch_node_abstract(
    conn: PoolConnectionProxy, user_id: int, node_id: int
) -> dict[str, Any] | None:
    record = await conn.fetchrow(
        "SELECT abstract FROM data_node_abstracts WHERE user_id = $1 AND node_id = $2",
        user_id,
        node_id,
    )
    return None if record is None else record["abstract"]


async def fetch_node_blob_count(
    conn: PoolConnectionProxy, user_id: int, node_id: int
) -> int | None:
    return await conn.fetchval(
        "SELECT blob_count FROM data_node_weights WHERE user_id = $1 AND node_id = $2",
        user_id,
        node_id,
    )


async def fetch_node_children(
    conn: PoolConnectionProxy, user_id: int, parent_node_id: int
) -> list[NodeChildView]:
    rows = await conn.fetch(
        """
        SELECT c.node_id, c.height, c.created_at,
               a.abstract,
               w.blob_count
        FROM data_node_edges e
        JOIN data_nodes c ON c.node_id = e.child_node_id
        LEFT JOIN data_node_abstracts a
          ON a.node_id = c.node_id AND a.user_id = $1
        LEFT JOIN data_node_weights w
          ON w.node_id = c.node_id AND w.user_id = $1
        WHERE e.user_id = $1 AND e.parent_node_id = $2
        ORDER BY w.blob_count DESC NULLS LAST, c.created_at
        """,
        user_id,
        parent_node_id,
    )
    return [
        NodeChildView(
            ref=node_ref(r["node_id"]),
            node_id=r["node_id"],
            height=r["height"],
            abstract=r["abstract"],
            blob_count=r["blob_count"],
        )
        for r in rows
    ]


async def fetch_blob_children(
    conn: PoolConnectionProxy, user_id: int, parent_node_id: int
) -> list[BlobChildView]:
    rows = await conn.fetch(
        """
        SELECT b.blob_id, b.abstract, b.file_id, b.file_blob_index,
               b.file_start, b.file_end
        FROM data_blob_edges e
        JOIN data_blobs b ON b.blob_id = e.child_blob_id
        WHERE e.user_id = $1 AND e.parent_node_id = $2
        ORDER BY b.file_id, b.file_blob_index
        """,
        user_id,
        parent_node_id,
    )
    return [
        BlobChildView(
            ref=blob_ref(r["blob_id"]),
            blob_id=r["blob_id"],
            abstract=r["abstract"],
            file_id=r["file_id"],
            file_blob_index=r["file_blob_index"],
            file_start=r["file_start"],
            file_end=r["file_end"],
        )
        for r in rows
    ]


async def fetch_children(
    conn: PoolConnectionProxy, user_id: int, node: NodeRow
) -> list[ChildView]:
    """Dispatch on node height: blobs at height 0, nodes everywhere else."""
    if node.height == 0:
        blobs = await fetch_blob_children(conn, user_id, node.node_id)
        return list(blobs)
    nodes = await fetch_node_children(conn, user_id, node.node_id)
    return list(nodes)
