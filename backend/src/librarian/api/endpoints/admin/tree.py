from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from librarian.api.core.auth.admin import require_admin
from librarian.api.db import DbConnection
from librarian.api.endpoints.data.tree import NodeView, build_node_view

# The admin tree is the user-facing /data/tree with the user picked
# explicitly rather than taken from the session cookie. It reuses the same
# NodeView + build_node_view — the only difference is where `user_id` comes
# from — so there is no second copy of the view-building logic to drift.
router = APIRouter(prefix="/admin/tree", dependencies=[Depends(require_admin)])


@router.get("/node", response_model=NodeView)
async def get_root(
    conn: DbConnection,
    user_id: Annotated[int, Query()],
) -> NodeView:
    view = await build_node_view(conn, user_id, None)
    if view is None:
        raise HTTPException(
            status_code=404,
            detail=f"No tree built yet for user {user_id}.",
        )
    return view


@router.get("/node/{node_id}", response_model=NodeView)
async def get_node(
    conn: DbConnection,
    node_id: int,
    user_id: Annotated[int, Query()],
) -> NodeView:
    view = await build_node_view(conn, user_id, node_id)
    if view is None:
        raise HTTPException(
            status_code=404,
            detail=f"Node {node_id} not found for user {user_id}",
        )
    return view
