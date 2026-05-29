from datetime import timedelta
from secrets import compare_digest, token_urlsafe
from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from librarian.api.core.auth.user import CurrentUser
from librarian.api.db import DbConnection
from librarian.api.http import HttpClient
from librarian.api.settings import settings
from librarian.common.crypto.fernet import encrypt as encrypt_google_token
from librarian.common.oauth.google.tokens import (
    build_authorize_url,
    exchange_code,
    fetch_user_info,
)
from librarian.db.tables.auth_google import AuthGoogle
from librarian.db.tables.auth_sessions import AuthSessions
from librarian.db.tables.users import Users

router = APIRouter(prefix="/oauth/google")

STATE_COOKIE = "oauth_state"
NEXT_COOKIE = "oauth_next"
STATE_TTL = timedelta(minutes=10)
CALLBACK_NAME = "oauth_google_callback"


def callback_url(request: Request) -> str:
    return str(request.url_for(CALLBACK_NAME))


def validate_next(value: str) -> str | None:
    """Accept only same-origin path-only redirects. Returns the validated
    value or None.

    Open-redirect defense: we never honour a `next=` that carries a scheme
    or host, even if it looks same-origin — string comparison against a
    configured allowlist is brittle and the only thing we actually want
    here is "send the user back to some path on this server". So enforce
    `next` starts with `/` (and not `//`, which most browsers parse as a
    protocol-relative URL).
    """
    if not value.startswith("/") or value.startswith("//"):
        return None
    return value


@router.get("/login")
async def login(request: Request, next: str | None = None) -> RedirectResponse:
    state = token_urlsafe(16)
    response = RedirectResponse(
        build_authorize_url(settings.google_oauth, callback_url(request), state)
    )
    response.set_cookie(
        key=STATE_COOKIE,
        value=state,
        max_age=int(STATE_TTL.total_seconds()),
        httponly=True,
        secure=settings.google_oauth.cookie_secure,
        samesite="lax",
    )
    # `next=` is honoured at /callback to support flows that need to come
    # back through a specific path (today: the MCP OAuth bridge endpoint).
    # We stash it in a short-lived cookie alongside the state cookie so
    # the value survives the round trip to Google.
    if next is not None:
        validated_next = validate_next(next)
        if validated_next is not None:
            response.set_cookie(
                key=NEXT_COOKIE,
                value=validated_next,
                max_age=int(STATE_TTL.total_seconds()),
                httponly=True,
                secure=settings.google_oauth.cookie_secure,
                samesite="lax",
            )
    return response


@router.get("/callback", name=CALLBACK_NAME)
async def callback(
    request: Request,
    conn: DbConnection,
    http: HttpClient,
    code: str | None = None,
    state: str | None = None,
    oauth_state: Annotated[str | None, Cookie(alias=STATE_COOKIE)] = None,
    oauth_next: Annotated[str | None, Cookie(alias=NEXT_COOKIE)] = None,
) -> RedirectResponse:
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")
    if not state or not oauth_state or not compare_digest(state, oauth_state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    redirect_uri = callback_url(request)
    tokens = await exchange_code(http, settings.google_oauth, code, redirect_uri)
    if tokens.refresh_token is None:
        raise HTTPException(
            status_code=400,
            detail="No refresh token returned by Google",
        )
    userinfo = await fetch_user_info(http, settings.google_oauth, tokens.access_token)

    refresh_token_enc = encrypt_google_token(
        settings.google_oauth.get_token_encryption_key, tokens.refresh_token
    )

    auth_google = AuthGoogle(conn)
    users = Users(conn)
    sessions = AuthSessions(conn)

    async with conn.transaction():
        existing = await auth_google.for_sub(userinfo.sub)
        if existing is not None:
            user_id = existing.user_id
            await auth_google.update_tokens(
                user_id=user_id,
                email=userinfo.email,
                refresh_token_enc=refresh_token_enc,
                scopes=tokens.scopes,
            )
        else:
            user_id = await users.create(user_name=userinfo.email)
            await auth_google.create(
                user_id=user_id,
                sub=userinfo.sub,
                email=userinfo.email,
                refresh_token_enc=refresh_token_enc,
                scopes=tokens.scopes,
            )
        session_id = await sessions.create(
            user_id=user_id,
            ttl=timedelta(days=settings.google_oauth.session_ttl_days),
        )

    # Honour a stashed `next=` path if it survived the round trip
    # (re-validated here in case the cookie was tampered with). Otherwise
    # fall back to the configured post-login URL (the FE root).
    next_target: str | None = None
    if oauth_next is not None:
        next_target = validate_next(oauth_next)
    redirect_target = next_target or settings.google_oauth.post_login_redirect
    response = RedirectResponse(redirect_target)
    response.delete_cookie(STATE_COOKIE)
    response.delete_cookie(NEXT_COOKIE)
    response.set_cookie(
        key=settings.cookies.session_cookie_name,
        value=session_id,
        max_age=int(
            timedelta(days=settings.google_oauth.session_ttl_days).total_seconds()
        ),
        httponly=True,
        secure=settings.google_oauth.cookie_secure,
        samesite="lax",
    )
    return response


@router.post("/logout", status_code=204)
async def logout(
    user_id: CurrentUser,
    conn: DbConnection,
    session_id: Annotated[
        str | None, Cookie(alias=settings.cookies.session_cookie_name)
    ] = None,
) -> Response:
    if session_id:
        await AuthSessions(conn).delete(session_id)
    response = Response(status_code=204)
    response.delete_cookie(settings.cookies.session_cookie_name)
    return response
