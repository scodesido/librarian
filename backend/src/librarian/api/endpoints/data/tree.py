from typing import Any

from asyncpg.pool import PoolConnectionProxy
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from librarian.api.core.auth.user import CurrentUser
from librarian.api.db import DbConnection
from librarian.db.tree_children import (
    ChildView,
    fetch_children,
    fetch_node_abstract,
    fetch_node_blob_count,
    fetch_node_row,
)

router = APIRouter(prefix="/data/tree")


class NodeView(BaseModel):
    node_id: int
    is_root: bool
    height: int
    abstract: dict[str, Any] | None
    blob_count: int | None
    children: list[ChildView]


async def build_node_view(
    conn: PoolConnectionProxy, user_id: int, node_id: int | None
) -> NodeView | None:
    node = await fetch_node_row(conn, user_id, node_id)
    if node is None:
        return None
    abstract = await fetch_node_abstract(conn, user_id, node.node_id)
    blob_count = await fetch_node_blob_count(conn, user_id, node.node_id)
    children = await fetch_children(conn, user_id, node)
    return NodeView(
        node_id=node.node_id,
        is_root=node.is_root,
        height=node.height,
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
