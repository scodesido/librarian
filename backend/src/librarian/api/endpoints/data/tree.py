from typing import Annotated, Any, Literal, Union

from asyncpg.pool import PoolConnectionProxy
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from librarian.api.core.auth.user import CurrentUser
from librarian.api.db import DbConnection

router = APIRouter(prefix="/data/tree")


class NodeChildView(BaseModel):
    kind: Literal["node"] = "node"
    node_id: int
    height: int
    abstract: dict[str, Any] | None
    blob_count: int | None


class BlobChildView(BaseModel):
    kind: Literal["blob"] = "blob"
    blob_id: int
    abstract: dict[str, Any]
    file_id: int
    file_blob_index: int
    file_start: int
    file_end: int


ChildView = Annotated[Union[NodeChildView, BlobChildView], Field(discriminator="kind")]


class NodeView(BaseModel):
    node_id: int
    is_root: bool
    height: int
    abstract: dict[str, Any] | None
    blob_count: int | None
    children: list[ChildView]


async def fetch_node_row(
    conn: PoolConnectionProxy, user_id: int, node_id: int | None
) -> dict[str, Any] | None:
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
    return None if record is None else dict(record)


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
            blob_id=r["blob_id"],
            abstract=r["abstract"],
            file_id=r["file_id"],
            file_blob_index=r["file_blob_index"],
            file_start=r["file_start"],
            file_end=r["file_end"],
        )
        for r in rows
    ]


async def build_node_view(
    conn: PoolConnectionProxy, user_id: int, node_id: int | None
) -> NodeView | None:
    node = await fetch_node_row(conn, user_id, node_id)
    if node is None:
        return None
    nid: int = node["node_id"]
    height: int = node["height"]
    abstract = await fetch_node_abstract(conn, user_id, nid)
    blob_count = await fetch_node_blob_count(conn, user_id, nid)
    children: list[ChildView]
    if height == 0:
        children = list(await fetch_blob_children(conn, user_id, nid))
    else:
        children = list(await fetch_node_children(conn, user_id, nid))
    return NodeView(
        node_id=nid,
        is_root=node["is_root"],
        height=height,
        abstract=abstract,
        blob_count=blob_count,
        children=children,
    )


@router.get("/node", response_model=NodeView)
async def get_root(user_id: CurrentUser, conn: DbConnection) -> NodeView:
    view = await build_node_view(conn, user_id, None)
    if view is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No tree built yet for this user. Sync some files and wait "
                "for the workers to finish, then try again."
            ),
        )
    return view


@router.get("/node/{node_id}", response_model=NodeView)
async def get_node(node_id: int, user_id: CurrentUser, conn: DbConnection) -> NodeView:
    view = await build_node_view(conn, user_id, node_id)
    if view is None:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
    return view
