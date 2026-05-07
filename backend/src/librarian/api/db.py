from contextlib import asynccontextmanager
from typing import Annotated, AsyncIterator

from asyncpg import Pool
from asyncpg.pool import PoolConnectionProxy
from fastapi import Depends, FastAPI, Request

from librarian.api.settings import settings
from librarian.db.connect import open_pool


@asynccontextmanager
async def attach_db_connection_pool(app: FastAPI) -> AsyncIterator[None]:
    async with open_pool(settings.database) as pool:
        app.state.db_connection_pool = pool
        try:
            yield
        finally:
            app.state.db_connection_pool = None


async def get_connection(
    request: Request,
) -> AsyncIterator[PoolConnectionProxy]:
    pool: Pool | None = request.app.state.db_connection_pool
    if pool is None:
        raise ValueError("No database connection pool available")
    async with pool.acquire() as conn:
        yield conn


DbConnection = Annotated[PoolConnectionProxy, Depends(get_connection)]
