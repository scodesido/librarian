from uvicorn import run

from librarian.api.settings import settings


def entrypoint():
    run(
        "librarian.api.app:create",
        factory=True,
        host=settings.api.host,
        port=settings.api.port,
        reload=settings.api.reload,
        workers=settings.api.workers,
        # When deployed behind a reverse proxy, trust X-Forwarded-Proto /
        # Host / Prefix so `request.url_for(...)` (used by the Google
        # OAuth callback URL) reflects the public-facing URL. Off by
        # default — see ApiSettings for the rationale.
        proxy_headers=settings.api.uvicorn_proxy_headers,
        forwarded_allow_ips=settings.api.uvicorn_forwarded_allow_ips,
    )
