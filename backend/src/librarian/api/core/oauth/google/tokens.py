from urllib.parse import urlencode

from aiohttp import ClientSession
from pydantic import BaseModel

from librarian.api.settings import settings


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str | None
    scopes: list[str]


class UserInfo(BaseModel):
    sub: str
    email: str


def build_authorize_url(redirect_uri: str, state: str) -> str:
    params = {
        "client_id": settings.google_oauth.get_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(settings.google_oauth.scopes),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{settings.google_oauth.auth_uri}?{urlencode(params)}"


async def exchange_code(
    http: ClientSession,
    code: str,
    redirect_uri: str,
) -> TokenResponse:
    async with http.post(
        settings.google_oauth.token_uri,
        data={
            "code": code,
            "client_id": settings.google_oauth.get_client_id,
            "client_secret": settings.google_oauth.get_client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    ) as resp:
        resp.raise_for_status()
        body = await resp.json()
    return TokenResponse(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token"),
        scopes=body.get("scope", "").split() or settings.google_oauth.scopes,
    )


async def refresh_access_token(
    http: ClientSession,
    refresh_token: str,
) -> str:
    async with http.post(
        settings.google_oauth.token_uri,
        data={
            "client_id": settings.google_oauth.get_client_id,
            "client_secret": settings.google_oauth.get_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    ) as resp:
        resp.raise_for_status()
        body = await resp.json()
    access_token: str = body["access_token"]
    return access_token


async def fetch_user_info(
    http: ClientSession,
    access_token: str,
) -> UserInfo:
    async with http.get(
        settings.google_oauth.user_info_uri,
        headers={"Authorization": f"Bearer {access_token}"},
    ) as resp:
        resp.raise_for_status()
        body = await resp.json()
    return UserInfo(sub=body["sub"], email=body["email"])
