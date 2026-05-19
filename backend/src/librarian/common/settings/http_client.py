from pydantic import BaseModel


class HttpClientSettings(BaseModel):
    # Total per-request timeout for the shared aiohttp session. Generous
    # by default because the same session carries calls with very
    # different latency profiles: OAuth refresh (~100 ms), Drive
    # listings (seconds), Drive file downloads (seconds to minutes),
    # ollama embedding batches (seconds, longer on first call when the
    # model is cold-loaded into VRAM). Tighten it via YAML config if a
    # specific environment wants faster failure on hangs.
    timeout: float = 60.0
    pool_size: int = 10
