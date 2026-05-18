from contextlib import asynccontextmanager
from typing import AsyncIterator

from aiohttp import ClientSession, ClientTimeout, TCPConnector

from librarian.common.settings.http_client import HttpClientSettings


@asynccontextmanager
async def open_client_session(
    settings: HttpClientSettings,
) -> AsyncIterator[ClientSession]:
    client = ClientSession(
        timeout=ClientTimeout(total=settings.timeout),
        connector=TCPConnector(limit=settings.pool_size),
    )
    try:
        yield client
    finally:
        await client.close()
