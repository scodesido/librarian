import hashlib


def token_hash(token: str) -> bytes:
    """Hash an opaque bearer token for at-rest storage.

    The OAuth access and refresh tokens we issue are 32+ bytes of secret
    entropy from `secrets.token_urlsafe` — already collision-resistant on
    their own. We hash before storage so a database leak doesn't leak the
    bearer credentials; a fixed sha256 (no salt, no pepper) is enough
    because the input already has full entropy and we need deterministic
    lookups on the bytes column.
    """
    return hashlib.sha256(token.encode()).digest()
