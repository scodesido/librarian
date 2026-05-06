from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from librarian.api.db.connect import attach_db_connection_pool
from librarian.api.endpoints.health import router as health_router
from librarian.api.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with attach_db_connection_pool(app):
        yield


def create() -> FastAPI:
    app = FastAPI()

    app.include_router(health_router)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api.cors_origins,
        allow_headers=settings.api.cors_headers,
        allow_methods=settings.api.cors_methods,
        allow_credentials=True,
    )

    return app
