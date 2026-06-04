from typing import Annotated, Any, Literal, Union

import numpy as np
from asyncpg.pool import PoolConnectionProxy
from numpy.typing import NDArray
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
            f"`peek_blob` / `list_file_blobs`, not `list_children`."
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
            f"`list_children` / `node_detail`, not `peek_blob`."
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
    # Cosine similarity of this child's centroid against the query embedding,
    # in [-1, 1]. Populated by the *_scored fetchers (retrieval path); None
    # for the unscored fetchers (tree-explorer path). Advisory only — the
    # agent is told it's for ranking siblings under one parent, not for
    # comparing across different parents.
    similarity_score: float | None = None


class BlobChildView(BaseModel):
    kind: Literal["blob"] = "blob"
    ref: str
    blob_id: int
    abstract: dict[str, Any]
    file_id: int
    file_blob_index: int
    file_start: int
    file_end: int
    # Human-readable name of the owning file (data_files.name). Populated only
    # by the unscored tree-explorer fetcher, where it's a debugging aid; the
    # agent-facing scored fetchers leave it None so the agent's projection (and
    # its prompt cache) is unaffected. None for files synced before the `name`
    # column existed (their stored name is the empty string — see the file_paths
    # migration), surfaced via NULLIF in the query.
    file_name: str | None = None
    # See NodeChildView.similarity_score. For blobs the similarity is against
    # `embedding_blob` (the text-only vector), not `embedding_with_file` —
    # the file-mixed variant is biased toward grouping same-file blobs and is
    # better suited to construction than retrieval.
    similarity_score: float | None = None


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
               b.file_start, b.file_end,
               NULLIF(f.name, '') AS file_name
        FROM data_blob_edges e
        JOIN data_blobs b ON b.blob_id = e.child_blob_id
        JOIN data_files f ON f.file_id = b.file_id
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
            file_name=r["file_name"],
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


async def fetch_node_children_scored(
    conn: PoolConnectionProxy,
    user_id: int,
    parent_node_id: int,
    query_embedding: NDArray[np.float32],
) -> list[NodeChildView]:
    """Same as fetch_node_children but each child carries a `similarity_score`
    computed in SQL as cosine similarity (`1 - centroid <=> $3`) between
    the parent's children's centroids and the user's query vector.

    `LEFT JOIN` on weights means a child without a weight row gets
    `similarity_score = NULL`; in practice the readiness gate ensures every
    node has a weight row before the agent is allowed to run, but the
    defensive None is still in the type.
    """
    rows = await conn.fetch(
        """
        SELECT c.node_id, c.height, c.created_at,
               a.abstract,
               w.blob_count,
               1 - (w.centroid <=> $3::vector) AS similarity_score
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
        query_embedding,
    )
    return [
        NodeChildView(
            ref=node_ref(r["node_id"]),
            node_id=r["node_id"],
            height=r["height"],
            abstract=r["abstract"],
            blob_count=r["blob_count"],
            similarity_score=(
                None if r["similarity_score"] is None else float(r["similarity_score"])
            ),
        )
        for r in rows
    ]


async def fetch_blob_children_scored(
    conn: PoolConnectionProxy,
    user_id: int,
    parent_node_id: int,
    query_embedding: NDArray[np.float32],
) -> list[BlobChildView]:
    """Same as fetch_blob_children but each child carries a `similarity_score`
    computed as cosine similarity against `embedding_blob` (NOT
    `embedding_with_file` — see BlobChildView.similarity_score).
    """
    rows = await conn.fetch(
        """
        SELECT b.blob_id, b.abstract, b.file_id, b.file_blob_index,
               b.file_start, b.file_end,
               1 - (b.embedding_blob <=> $3::vector) AS similarity_score
        FROM data_blob_edges e
        JOIN data_blobs b ON b.blob_id = e.child_blob_id
        WHERE e.user_id = $1 AND e.parent_node_id = $2
        ORDER BY b.file_id, b.file_blob_index
        """,
        user_id,
        parent_node_id,
        query_embedding,
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
            similarity_score=(
                None if r["similarity_score"] is None else float(r["similarity_score"])
            ),
        )
        for r in rows
    ]


async def fetch_blob_file_id(
    conn: PoolConnectionProxy, user_id: int, blob_id: int
) -> int | None:
    """The owning file of a blob, or None if the blob doesn't exist for this
    user. Used by `list_file_blobs` to resolve a blob ref to its file before
    listing the file's blobs.
    """
    return await conn.fetchval(
        "SELECT file_id FROM data_blobs WHERE user_id = $1 AND blob_id = $2",
        user_id,
        blob_id,
    )


async def fetch_file_blobs_scored(
    conn: PoolConnectionProxy,
    user_id: int,
    file_id: int,
    query_embedding: NDArray[np.float32],
    limit: int,
    offset: int,
) -> tuple[list[BlobChildView], int]:
    """One page of a file's blobs, in document order (`file_blob_index`), each
    carrying a `similarity_score` against `embedding_blob` (same column choice
    as `fetch_blob_children_scored`). Returns the page plus the file's total
    blob count (via a window aggregate) so the caller can paginate.

    Unlike the *_children fetchers this walks `data_blobs` directly by
    `file_id` rather than the tree edges — the point is document adjacency,
    which is orthogonal to tree structure.
    """
    rows = await conn.fetch(
        """
        SELECT b.blob_id, b.abstract, b.file_id, b.file_blob_index,
               b.file_start, b.file_end,
               1 - (b.embedding_blob <=> $3::vector) AS similarity_score,
               count(*) OVER () AS total
        FROM data_blobs b
        WHERE b.user_id = $1 AND b.file_id = $2
        ORDER BY b.file_blob_index
        LIMIT $4 OFFSET $5
        """,
        user_id,
        file_id,
        query_embedding,
        limit,
        offset,
    )
    total = int(rows[0]["total"]) if rows else 0
    page = [
        BlobChildView(
            ref=blob_ref(r["blob_id"]),
            blob_id=r["blob_id"],
            abstract=r["abstract"],
            file_id=r["file_id"],
            file_blob_index=r["file_blob_index"],
            file_start=r["file_start"],
            file_end=r["file_end"],
            similarity_score=(
                None if r["similarity_score"] is None else float(r["similarity_score"])
            ),
        )
        for r in rows
    ]
    return page, total


async def fetch_children_scored(
    conn: PoolConnectionProxy,
    user_id: int,
    node: NodeRow,
    query_embedding: NDArray[np.float32],
) -> list[ChildView]:
    """Scored variant of fetch_children: dispatches on node height and
    attaches a cosine similarity to each child. See the docstrings on
    fetch_node_children_scored / fetch_blob_children_scored for the
    column choice rationale.
    """
    if node.height == 0:
        blobs = await fetch_blob_children_scored(
            conn, user_id, node.node_id, query_embedding
        )
        return list(blobs)
    nodes = await fetch_node_children_scored(
        conn, user_id, node.node_id, query_embedding
    )
    return list(nodes)
