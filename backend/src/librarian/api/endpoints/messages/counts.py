from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel

from librarian.api.core.auth.user import CurrentUser
from librarian.api.db import DbConnection
from librarian.db.tables.user_worker_events import EventCountModel, UserWorkerEvents

router = APIRouter(prefix="/messages")


class CountsResponse(BaseModel):
    """Per-`code` event counts for the current user over the requested
    window, ascending by code. The FE folds these into per-band badges
    (category = code // 1000) without pulling every row.
    """

    since: datetime
    counts: list[EventCountModel]


@router.get("/counts", response_model=CountsResponse)
async def get_counts(
    user_id: CurrentUser,
    conn: DbConnection,
    since_days: int = Query(default=30, ge=1, le=365),
) -> CountsResponse:
    """Counts grouped by event code over the last `since_days` days, each
    with its latest occurrence.
    """
    since = datetime.now(timezone.utc) - timedelta(days=since_days)
    counts = await UserWorkerEvents(conn).counts(user_id, since)
    return CountsResponse(since=since, counts=counts)
