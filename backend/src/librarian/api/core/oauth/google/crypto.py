from cryptography.fernet import Fernet

from librarian.api.settings import settings


def fernet() -> Fernet:
    key = settings.google_oauth.get_token_encryption_key
    return Fernet(key.encode())


def encrypt(token: str) -> bytes:
    return fernet().encrypt(token.encode())


def decrypt(token_enc: bytes) -> str:
    return fernet().decrypt(bytes(token_enc)).decode()
