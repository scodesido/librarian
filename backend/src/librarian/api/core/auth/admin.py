import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException

from librarian.api.settings import settings


async def require_admin(
    x_admin_password: Annotated[str | None, Header()] = None,
) -> None:
    """Gate the /admin endpoints behind the operator's single admin
    password, passed as the `X-Admin-Password` header.

    Two distinct refusals: 503 when no password is configured (admin is
    disabled for this environment — fail loud rather than fall open), and
    401 when the header is missing or wrong. The compare is constant-time
    so a wrong password leaks no timing signal.
    """
    configured = settings.admin.password
    if configured is None:
        raise HTTPException(status_code=503, detail="Admin panel is not configured")
    if x_admin_password is None or not secrets.compare_digest(
        x_admin_password, configured.get_secret_value()
    ):
        raise HTTPException(status_code=401, detail="Invalid admin password")


RequireAdmin = Annotated[None, Depends(require_admin)]
