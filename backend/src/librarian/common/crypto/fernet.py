from cryptography.fernet import Fernet


def encrypt(key: str, token: str) -> bytes:
    return Fernet(key.encode()).encrypt(token.encode())


def decrypt(key: str, token_enc: bytes) -> str:
    return Fernet(key.encode()).decrypt(bytes(token_enc)).decode()
