from uvicorn import run

from librarian.api.settings import settings


def entrypoint():
    run(
        "librarian.api.app:create",
        factory=True,
        host=settings.api.host,
        port=settings.api.port,
        reload=settings.api.reload,
        root_path=settings.api.root_path,
        workers=settings.api.workers,
    )
