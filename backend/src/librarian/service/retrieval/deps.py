import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import numpy as np
from aiohttp import ClientSession
from asyncpg.pool import PoolConnectionProxy
from numpy.typing import NDArray

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

    `search_embedding` is the L2-normalised vector of the user's search
    terms (defaulting to the question if no explicit terms were provided),
    embedded with the same model used to index the library. Every child
    fetch in the agent loop pgvector-scores against it and surfaces a
    cosine similarity per child — advisory information the agent uses to
    rank siblings under one parent.

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
    search_embedding: NDArray[np.float32]
    emit: Callable[[QueryEvent], Awaitable[None]] | None = None
    step_count: int = 0
    content_fetch_count: int = 0
    detail_fetch_count: int = 0
    blob_detail_fetch_count: int = 0
    file_listing_count: int = 0
    # Serialises access to the single shared `conn`. pydantic-ai runs the tool
    # calls of one model turn concurrently (asyncio.gather), but an asyncpg
    # connection cannot be used by two coroutines at once ("another operation is
    # in progress"). Every tool holds this lock around its DB work, so parallel
    # tool calls queue on the connection instead of colliding. Per-request, so
    # it only serialises one query's own tools — never across requests.
    db_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Every node/blob ref the agent has actually been shown — the seed's refs
    # at construction, then every ref returned by list_children / list_file_blobs
    # as the walk proceeds. The tools reject any ref not in this set (see
    # `provenance.py`): node and blob id spaces are disjoint at the DB level
    # (shared sequence), so a fabricated ref can't accidentally resolve to the
    # wrong kind — but it could still name a real same-kind element the agent
    # never saw, and the agent could hallucinate one outright. Gating on
    # provenance closes both: a ref the agent didn't reach by descent is refused.
    seen_refs: set[str] = field(default_factory=set)
