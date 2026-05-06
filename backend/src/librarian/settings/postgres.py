from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, SecretStr


class PostgresSettings(BaseModel):
    user: str = "admin"
    password: SecretStr | None = None
    host: str = "postgres"
    port: int = 5432
    name: str = "librarian"
    ssl_mode: Literal["disable", "prefer", "require", "verify-ca", "verify-full"] = (
        "disable"
    )
    min_connections: int = 1
    max_connections: int = 10

    @property
    def url(self) -> str:
        if self.password is None:
            raise ValueError("Postgres password is required")

        encoded_password = quote(self.password.get_secret_value(), safe="")
        return (
            f"postgres://{self.user}:"
            f"{encoded_password}@"
            f"{self.host}:"
            f"{self.port}/"
            f"{self.name}?"
            f"sslmode={self.ssl_mode}"
        )
