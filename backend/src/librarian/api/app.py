from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from librarian.api.db import attach_db_connection_pool
from librarian.api.endpoints.auth.me import router as auth_me_router
from librarian.api.endpoints.data.files import router as data_files_router
from librarian.api.endpoints.data.query import router as data_query_router
from librarian.api.endpoints.data.tree import router as data_tree_router
from librarian.api.endpoints.health import router as health_router
from librarian.api.endpoints.oauth.google import router as oauth_google_router
from librarian.api.http import attach_http_client
from librarian.api.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with (
        attach_db_connection_pool(app),
        attach_http_client(app),
    ):
        yield


def create() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    app.include_router(health_router)
    app.include_router(oauth_google_router)
    app.include_router(auth_me_router)
    app.include_router(data_files_router)
    app.include_router(data_tree_router)
    app.include_router(data_query_router)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api.cors_origins,
        allow_headers=settings.api.cors_headers,
        allow_methods=settings.api.cors_methods,
        allow_credentials=True,
    )

    return app
