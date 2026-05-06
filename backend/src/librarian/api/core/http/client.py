from contextlib import asynccontextmanager
from typing import Annotated, AsyncIterator

from aiohttp import ClientSession, ClientTimeout, TCPConnector
from fastapi import Depends, FastAPI, Request

from librarian.api.settings import settings


@asynccontextmanager
async def attach_http_client(app: FastAPI) -> AsyncIterator[None]:
    client = ClientSession(
        timeout=ClientTimeout(total=settings.http_client.timeout),
        connector=TCPConnector(limit=settings.http_client.pool_size),
    )
    try:
        app.state.http_client = client
        yield
    finally:
        app.state.http_client = None
        await client.close()


async def get_http_client(request: Request) -> ClientSession:
    client: ClientSession | None = request.app.state.http_client
    if client is None:
        raise ValueError("No HTTP client available")
    return client


HttpClient = Annotated[ClientSession, Depends(get_http_client)]
