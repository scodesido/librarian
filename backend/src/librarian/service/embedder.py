from typing import Protocol

import numpy as np
from aiohttp import ClientSession
from numpy.typing import NDArray


class Embedder(Protocol):
    """A minimal embedder interface used across the librarian service. One
    method, one batched call, returns one float32 vector per input. Each
    implementation talks to a single provider via direct HTTP — we deliberately
    don't go through pydantic-ai for embeddings because the wrapper buys
    little, and a thin per-provider class lets us add providers (or unusual
    transports like a local ollama daemon) without taking a dependency on
    whatever pydantic-ai's embedder layer happens to support.
    """

    async def embed_documents(
        self, http: ClientSession, inputs: list[str]
    ) -> list[NDArray[np.float32]]: ...


class OllamaEmbedder:
    """Local-first embedder via an ollama daemon.

    ollama's /api/embed accepts a batched input list and returns one
    embedding per input. For embedding models that support Matryoshka
    truncation (e.g. qwen3-embedding), the `dimensions` parameter caps the
    returned dimensionality server-side. ollama silently ignores it for
    models that don't support truncation; the resulting size mismatch with
    the vector(1024) column then surfaces clearly at INSERT time.
    """

    def __init__(self, host: str, model: str, dimensions: int) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.dimensions = dimensions

    async def embed_documents(
        self, http: ClientSession, inputs: list[str]
    ) -> list[NDArray[np.float32]]:
        async with http.post(
            f"{self.host}/api/embed",
            json={
                "model": self.model,
                "input": inputs,
                "dimensions": self.dimensions,
            },
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
        return [np.asarray(e, dtype=np.float32) for e in data["embeddings"]]


class VoyageEmbedder:
    """Voyage AI hosted embedder. Direct HTTP rather than the voyageai SDK
    or pydantic-ai's wrapper, so the only thing we depend on is the public
    /v1/embeddings contract.

    `output_dimension` is sent unconditionally; Voyage only supports it on
    certain models (voyage-3-large, voyage-3.5, voyage-3.5-lite, voyage-code-3).
    On models that don't support it the API returns 400, which the
    blob_extractor surfaces via its standard exception-backoff path.
    """

    def __init__(self, api_key: str, model: str, dimensions: int) -> None:
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions

    async def embed_documents(
        self, http: ClientSession, inputs: list[str]
    ) -> list[NDArray[np.float32]]:
        async with http.post(
            "https://api.voyageai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "input": inputs,
                "input_type": "document",
                "output_dimension": self.dimensions,
            },
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
        # Voyage returns objects with an `index` field; the API guarantees
        # them in input order, but sort defensively in case that ever
        # changes.
        ordered = sorted(data["data"], key=lambda d: d["index"])
        return [np.asarray(d["embedding"], dtype=np.float32) for d in ordered]
