from pydantic import BaseModel, SecretStr


class UserTokensSettings(BaseModel):
    """Operator-side configuration for the `user_slot_tokens` table.

    `encryption_key` is the Fernet key used to encrypt/decrypt user-
    supplied API tokens at rest. Same threat model as
    `google_oauth.token_encryption_key`: a DB leak should not become a
    credential leak. Kept separate from the Google one so the two can
    be rotated independently (rotating the user-token key does not
    invalidate stored Google refresh tokens, and vice versa).
    """

    encryption_key: SecretStr | None = None

    @property
    def get_encryption_key(self) -> str:
        if self.encryption_key is None:
            raise ValueError("user_tokens.encryption_key is not configured")
        return self.encryption_key.get_secret_value()
