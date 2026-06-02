from datetime import datetime, timedelta, timezone
from typing import Iterator

from asyncpg import Pool
from asyncpg.pool import PoolConnectionProxy

from librarian.common.oauth.google.access import NoGoogleAuthError
from librarian.db.tables.user_worker_events import (
    EventCode,
    Source,
    UserWorkerEvents,
)
from librarian.service.credentials import MissingTokenError


def cause_chain(exc: BaseException, max_depth: int = 8) -> Iterator[BaseException]:
    """Yield `exc` and its `__cause__` chain, bounded so a self-referential
    cause can't loop. `process_file` wraps `NoGoogleAuthError` into a
    `ProcessFileError` (with `raise ... from`), so classification has to
    look past the outermost type to recover the user-actionable cause.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and len(seen) < max_depth and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__


def http_status(exc: BaseException) -> int | None:
    """Best-effort HTTP status pulled off a provider exception (or its
    cause). Provider SDKs / pydantic-ai surface it as `.status_code` or
    `.response.status_code`; anything else yields None.
    """
    for current in cause_chain(exc):
        status = getattr(current, "status_code", None)
        if status is None:
            response = getattr(current, "response", None)
            status = getattr(response, "status_code", None)
        if isinstance(status, int):
            return status
    return None


def classify_exception(exc: BaseException) -> EventCode:
    """Map a worker exception to an EventCode. Owned, typed exceptions
    classify precisely (walking the cause chain); provider HTTP statuses
    map 429/401/403/5xx; everything unrecognised falls back to
    `INTERNAL_ERROR`. We never guess a 4xxx (user-actionable) from an
    unknown exception — mislabelling our own bug as "your fault, fix it in
    Settings" is worse than a generic internal-error bucket.

    `ProcessFileError` / `ProcessNodeError` are matched by name rather
    than imported: importing the worker process modules here would create
    a cycle (they import `record_event` from this module).
    """
    for current in cause_chain(exc):
        if isinstance(current, MissingTokenError):
            return EventCode.MISSING_TOKEN
        if isinstance(current, NoGoogleAuthError):
            return EventCode.MISSING_GOOGLE_AUTH

    status = http_status(exc)
    if status == 429:
        return EventCode.PROVIDER_RATE_LIMITED
    if status in (401, 403):
        return EventCode.INVALID_TOKEN
    if status is not None and 500 <= status < 600:
        return EventCode.PROVIDER_UNAVAILABLE

    for current in cause_chain(exc):
        if type(current).__name__ in ("ProcessFileError", "ProcessNodeError"):
            return EventCode.PIPELINE_ERROR

    return EventCode.INTERNAL_ERROR


async def record_event(
    conn: PoolConnectionProxy,
    user_id: int,
    code: EventCode,
    source: Source,
    detail: str | None = None,
    context: dict | None = None,
    throttle_window: float | None = None,
) -> None:
    """Append one row to `user_worker_events` on `conn`.

    The caller chooses the connection per the "match the event's fate to
    the work's" rule (doc 15): success and caught-failure events pass the
    work `conn` so they commit with the work; the rolled-back
    propagated-failure path uses a fresh connection (see `record_failure`).

    `throttle_window`, when set, deduplicates: if an identical
    `(user_id, code, source)` row already exists within that many seconds,
    the insert is skipped. Failures pass a window to tame the broken-token
    flood (workers re-pick the same user at random with no cooldown);
    per-unit milestones like FILE_PROCESSED pass None so every distinct
    file is recorded.
    """
    events = UserWorkerEvents(conn)
    if throttle_window is not None:
        since = datetime.now(timezone.utc) - timedelta(seconds=throttle_window)
        if await events.exists_recent(user_id, int(code), source, since):
            return
    await events.insert(user_id, int(code), source, detail, context)


async def record_failure(
    pool: Pool,
    user_id: int,
    exc: BaseException,
    source: Source,
    throttle_window: float,
    context: dict | None = None,
) -> None:
    """Record a worker failure on a FRESH pool connection, decoupled from
    the work transaction that is rolling back. Classifies `exc` and always
    throttles (failures are the flood-prone path). This is the only seam
    that must not reuse the doomed work `conn`.
    """
    code = classify_exception(exc)
    async with pool.acquire() as conn:
        await record_event(
            conn,
            user_id,
            code,
            source,
            detail=str(exc),
            context=context,
            throttle_window=throttle_window,
        )
