from contextlib import asynccontextmanager
from typing import Annotated, AsyncIterator

from asyncpg import Connection, Pool, create_pool
from asyncpg.pool import PoolConnectionProxy
from fastapi import Depends, FastAPI, Request

from librarian.api.settings import settings


@asynccontextmanager
async def attach_db_connection_pool(app: FastAPI) -> AsyncIterator[None]:
    pool = await create_pool(
        dsn=settings.database.url,
        min_size=settings.database.min_connections,
        max_size=settings.database.max_connections,
    )
    try:
        app.state.db_connection_pool = pool
        yield
    finally:
        app.state.db_connection_pool = None
        await pool.close()


async def get_connection(
    request: Request,
) -> AsyncIterator[PoolConnectionProxy]:
    pool: Pool | None = request.state.db_connection_pool
    if pool is None:
        raise ValueError("No database connection pool available")

    async with pool.acquire() as conn:
        yield conn


DbConnection = Annotated[Connection, Depends(get_connection)]
