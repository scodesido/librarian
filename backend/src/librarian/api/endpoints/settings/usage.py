from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel

from librarian.api.core.auth.user import CurrentUser
from librarian.api.db import DbConnection
from librarian.db.tables.user_token_usage import UsageAggregate, UserTokenUsage

router = APIRouter(prefix="/settings/usage")


class UsageResponse(BaseModel):
    """Aggregated per-(operation, provider, model) token usage for the
    current user over the requested window. `since` echoes the window's
    lower bound so the FE can label the table without recomputing it.
    """

    since: datetime
    aggregates: list[UsageAggregate]


@router.get("", response_model=UsageResponse)
async def get_usage(
    user_id: CurrentUser,
    conn: DbConnection,
    since_days: int = Query(default=30, ge=1, le=365),
) -> UsageResponse:
    """Per-(operation, provider, model) sums over the last `since_days`
    days, ordered by SUM(input_tokens) DESC. The hard cap of 365 days
    is defensive — bigger windows would still execute in PG (the table
    has a `(user_id, created_at)` index) but no FE today wants more.
    """
    since = datetime.now(timezone.utc) - timedelta(days=since_days)
    aggregates = await UserTokenUsage(conn).aggregate(user_id, since)
    return UsageResponse(since=since, aggregates=aggregates)
