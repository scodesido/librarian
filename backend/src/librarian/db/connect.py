import json
from contextlib import asynccontextmanager
from typing import AsyncIterator

from asyncpg import Connection, Pool, create_pool
from pgvector.asyncpg import register_vector

from librarian.common.settings.postgres import PostgresSettings


async def init_connection(conn: Connection) -> None:
    for typename in ("json", "jsonb"):
        await conn.set_type_codec(
            typename,
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )
    await register_vector(conn)


@asynccontextmanager
async def open_pool(settings: PostgresSettings) -> AsyncIterator[Pool]:
    pool = await create_pool(
        dsn=settings.url,
        min_size=settings.min_connections,
        max_size=settings.max_connections,
        init=init_connection,
    )
    try:
        yield pool
    finally:
        await pool.close()
