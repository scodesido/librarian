from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel

from librarian.api.core.auth.user import CurrentUser
from librarian.api.db import DbConnection
from librarian.db.tables.user_worker_events import (
    UserWorkerEventModel,
    UserWorkerEvents,
)

router = APIRouter(prefix="/messages")


class RecentResponse(BaseModel):
    """Newest-first worker events for the current user over the requested
    window. `since` echoes the window's lower bound so the FE can label
    the list without recomputing it.
    """

    since: datetime
    events: list[UserWorkerEventModel]


@router.get("/recent", response_model=RecentResponse)
async def get_recent(
    user_id: CurrentUser,
    conn: DbConnection,
    since_days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=50, ge=1, le=200),
    category: int | None = Query(default=None, ge=1, le=4),
) -> RecentResponse:
    """The user's most recent worker events, newest first. `category`
    (1=info, 2=internal, 3=provider, 4=user-actionable) optionally
    restricts to one band. The 365-day cap mirrors /settings/usage — the
    `(user_id, created_at)` index would still serve a wider window, but no
    FE wants one.
    """
    since = datetime.now(timezone.utc) - timedelta(days=since_days)
    events = await UserWorkerEvents(conn).recent(user_id, since, limit, category)
    return RecentResponse(since=since, events=events)
