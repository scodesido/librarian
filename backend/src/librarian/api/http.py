from contextlib import asynccontextmanager
from typing import Annotated, AsyncIterator

from aiohttp import ClientSession
from fastapi import Depends, FastAPI, Request

from librarian.api.settings import settings
from librarian.http.client import open_client_session


@asynccontextmanager
async def attach_http_client(app: FastAPI) -> AsyncIterator[None]:
    async with open_client_session(settings.http_client) as client:
        app.state.http_client = client
        try:
            yield
        finally:
            app.state.http_client = None


async def get_http_client(request: Request) -> ClientSession:
    client: ClientSession | None = request.app.state.http_client
    if client is None:
        raise ValueError("No HTTP client available")
    return client


HttpClient = Annotated[ClientSession, Depends(get_http_client)]
