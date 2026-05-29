from aiohttp import ClientSession
from asyncpg.pool import PoolConnectionProxy

from librarian.common.crypto.fernet import decrypt as decrypt_google_token
from librarian.common.oauth.google.tokens import refresh_access_token
from librarian.common.settings.google_oauth import GoogleOAuthSettings
from librarian.db.tables.auth_google import AuthGoogle


class NoGoogleAuthError(Exception):
    """Raised when the user has no row in auth_google."""


async def access_token_for_user(
    conn: PoolConnectionProxy,
    http: ClientSession,
    settings: GoogleOAuthSettings,
    user_id: int,
) -> str:
    """Fetch the user's stored refresh token, decrypt it, and exchange it
    for a fresh access token. Single seam shared by every caller that needs
    to act as the user against Google APIs (sync, blob_extractor, retrieval).
    """
    auth = await AuthGoogle(conn).for_user(user_id)
    if auth is None:
        raise NoGoogleAuthError(f"user {user_id} has no google auth")
    refresh_token = decrypt_google_token(
        settings.get_token_encryption_key, auth.refresh_token_enc
    )
    return await refresh_access_token(http, settings, refresh_token)
