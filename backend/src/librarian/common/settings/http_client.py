from pydantic import BaseModel


class HttpClientSettings(BaseModel):
    timeout: float = 10.0
    pool_size: int = 10
