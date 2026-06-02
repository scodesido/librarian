from datetime import datetime
from enum import IntEnum
from typing import Literal

from pydantic import BaseModel

from librarian.db.table import Table, TableModel


class EventCode(IntEnum):
    """Closed vocabulary of worker-event reasons. The thousands digit is
    the category (`code // 1000`): 1xxx informational, 2xxx internal,
    3xxx external provider, 4xxx user-actionable. The DB CHECK pins only
    the 1000..4999 band as a range, so adding a code here needs no
    migration — this enum is the source of truth for which codes are live.

    Only 4xxx codes get the FE's "Fix in Settings" affordance, so the
    classifier must never guess a 4xxx from an unrecognised exception (see
    service/events.classify_exception).
    """

    # 1xxx — informational / success milestones.
    FILE_PROCESSED = 1001
    LIBRARY_ABSTRACTED = 1002

    # 2xxx — internal errors (our bug / invariant violation).
    INTERNAL_ERROR = 2001
    PIPELINE_ERROR = 2002

    # 3xxx — external provider errors (transient; the user waits it out).
    PROVIDER_RATE_LIMITED = 3001
    PROVIDER_UNAVAILABLE = 3002

    # 4xxx — user-actionable config (fixable from the Settings tab).
    MISSING_TOKEN = 4001
    INVALID_TOKEN = 4002
    MISSING_GOOGLE_AUTH = 4003


# Which background worker emitted the event. Mirrors the DB CHECK in
# 202606020001_user_errors.sql. The synchronous paths (retrieval, sync)
# surface their errors inline and are deliberately absent — see doc 15.
Source = Literal["blob_extractor", "node_extractor", "tree_builder"]


class UserWorkerEventModel(TableModel):
    """One row of the ledger. `code` is read back as a plain int (not
    EventCode) so a row written by a newer worker during a rolling deploy
    can't fail validation on an older reader; the FE derives the category
    as `code // 1000`.
    """

    event_id: int
    user_id: int
    code: int
    source: str
    detail: str | None
    context: dict | None
    created_at: datetime


class EventCountModel(BaseModel):
    """One aggregated bucket over `user_worker_events`, grouped by `code`
    within the caller's window. `latest_at` is the most recent occurrence
    so the FE can show "last seen" without a second query.
    """

    code: int
    count: int
    latest_at: datetime


SELECT_COLUMNS = "event_id, user_id, code, source, detail, context, created_at"


class UserWorkerEvents(Table):
    async def insert(
        self,
        user_id: int,
        code: int,
        source: Source,
        detail: str | None,
        context: dict | None,
    ) -> None:
        await self.conn.execute(
            (
                "INSERT INTO user_worker_events "
                "(user_id, code, source, detail, context) "
                "VALUES ($1, $2, $3, $4, $5)"
            ),
            user_id,
            code,
            source,
            detail,
            context,
        )

    async def exists_recent(
        self, user_id: int, code: int, source: Source, since: datetime
    ) -> bool:
        """Whether an identical `(user_id, code, source)` row exists with
        `created_at >= since`. Backs the write throttle in
        service/events.record_event; uses the
        `(user_id, created_at DESC)` index.
        """
        return bool(
            await self.conn.fetchval(
                "SELECT EXISTS ("
                "  SELECT 1 FROM user_worker_events "
                "  WHERE user_id = $1 AND code = $2 AND source = $3 "
                "    AND created_at >= $4"
                ")",
                user_id,
                code,
                source,
                since,
            )
        )

    async def recent(
        self,
        user_id: int,
        since: datetime,
        limit: int,
        category: int | None = None,
    ) -> list[UserWorkerEventModel]:
        """Newest-first events for `user_id` with `created_at >= since`.
        `category` (1..4), when given, restricts to that band via a
        `code BETWEEN category*1000 AND category*1000+999` predicate.
        """
        if category is None:
            rows = await self.conn.fetch(
                f"SELECT {SELECT_COLUMNS} FROM user_worker_events "
                "WHERE user_id = $1 AND created_at >= $2 "
                "ORDER BY created_at DESC LIMIT $3",
                user_id,
                since,
                limit,
            )
        else:
            low = category * 1000
            rows = await self.conn.fetch(
                f"SELECT {SELECT_COLUMNS} FROM user_worker_events "
                "WHERE user_id = $1 AND created_at >= $2 "
                "  AND code BETWEEN $3 AND $4 "
                "ORDER BY created_at DESC LIMIT $5",
                user_id,
                since,
                low,
                low + 999,
                limit,
            )
        return [UserWorkerEventModel.model_validate(dict(r)) for r in rows]

    async def counts(self, user_id: int, since: datetime) -> list[EventCountModel]:
        """Per-`code` counts (and latest occurrence) for `user_id` over
        rows with `created_at >= since`, ordered by `code` so the FE
        renders bands in ascending order.
        """
        rows = await self.conn.fetch(
            "SELECT code, COUNT(*) AS count, MAX(created_at) AS latest_at "
            "FROM user_worker_events "
            "WHERE user_id = $1 AND created_at >= $2 "
            "GROUP BY code ORDER BY code",
            user_id,
            since,
        )
        return [EventCountModel.model_validate(dict(r)) for r in rows]
