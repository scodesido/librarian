from dataclasses import dataclass, field
from typing import Awaitable, Callable

from aiohttp import ClientSession
from asyncpg.pool import PoolConnectionProxy

from librarian.api.settings import QuerySettings
from librarian.service.retrieval.events import QueryEvent
from librarian.service.retrieval.providers import BlobContentProvider


@dataclass
class QueryDeps:
    """Mutable per-request state, passed to every tool via `RunContext.deps`.

    The endpoint constructs this once per request, then hands it to
    `agent.run`. `step_count` and `content_fetch_count` are bumped by the
    tools; `budget` is fixed at construction. `emit` is None for the
    non-streaming response path and a queue-push callable for the SSE path.

    Lives in its own module so both `tools.py` (which references it via
    `RunContext[QueryDeps]`) and `agent.py` (which constructs it and registers
    the tools) can import it without a circular dependency.
    """

    conn: PoolConnectionProxy
    http: ClientSession
    user_id: int
    settings: QuerySettings
    provider: BlobContentProvider
    budget: int
    emit: Callable[[QueryEvent], Awaitable[None]] | None = None
    step_count: int = 0
    content_fetch_count: int = 0
    visited_node_ids: list[int] = field(default_factory=list)
