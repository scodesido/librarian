from dataclasses import dataclass
from typing import Protocol

import numpy as np
from aiohttp import ClientSession
from numpy.typing import NDArray

from librarian.common.settings.model_catalog import split_model


@dataclass(frozen=True)
class EmbedResult:
    """What an `Embedder.embed_documents` call returns: one vector per
    input plus the provider-reported input token count (0 if the
    provider doesn't surface one). The token count flows into the
    usage ledger; callers that only care about the vectors can read
    `.vectors` and ignore `.input_tokens`.
    """

    vectors: list[NDArray[np.float32]]
    input_tokens: int


def normalize_l2(vec: NDArray[np.float32]) -> NDArray[np.float32]:
    norm = float(np.linalg.norm(vec))
    if norm == 0.0:
        return vec
    return (vec / norm).astype(np.float32)


def split_long_paragraph(
    para: str, target_chars: int, hard_max_chars: int
) -> list[str]:
    """Break a paragraph too long to fit in one chunk. Each cut goes at
    the first whitespace at position >= target_chars from the chunk's
    start; if no whitespace exists in [target_chars, hard_max_chars), we
    fall back to a hard cut at hard_max_chars to avoid unbounded chunks
    on whitespace-free input (tables, base64, etc.).
    """
    chunks: list[str] = []
    start = 0
    n = len(para)
    while start < n:
        if n - start <= hard_max_chars:
            chunks.append(para[start:])
            break
        search_start = start + target_chars
        search_end = start + hard_max_chars
        end = search_end
        for i in range(search_start, search_end):
            if para[i].isspace():
                end = i
                break
        chunks.append(para[start:end])
        start = end
    return chunks


def chunk_for_embedding(text: str, target_chars: int, hard_max_chars: int) -> list[str]:
    """Split `text` into chunks bounded by `hard_max_chars`. Pack
    paragraphs (separated by blank lines) greedily until the next one
    would overflow `target_chars`; force-split a single oversized
    paragraph via `split_long_paragraph`.

    Returns at least one chunk for any non-empty `text`. A short `text`
    that already fits returns as a single-element list, so callers don't
    need to special-case "no chunking needed".
    """
    if hard_max_chars < target_chars:
        raise ValueError(
            f"hard_max_chars ({hard_max_chars}) must be >= target_chars "
            f"({target_chars})"
        )
    if len(text) <= target_chars:
        return [text]
    chunks: list[str] = []
    buf = ""
    for para in text.split("\n\n"):
        if not para:
            continue
        if len(para) > target_chars:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.extend(split_long_paragraph(para, target_chars, hard_max_chars))
            continue
        candidate = f"{buf}\n\n{para}" if buf else para
        if len(candidate) > target_chars:
            chunks.append(buf)
            buf = para
        else:
            buf = candidate
    if buf:
        chunks.append(buf)
    return chunks


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
    ) -> EmbedResult: ...


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
    ) -> EmbedResult:
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
        # Ollama returns `prompt_eval_count` summed across the batch.
        # Missing on some model/version combinations; coerce to 0 so the
        # ledger row stays valid against the non-negative CHECK.
        return EmbedResult(
            vectors=[np.asarray(e, dtype=np.float32) for e in data["embeddings"]],
            input_tokens=int(data.get("prompt_eval_count", 0) or 0),
        )


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
    ) -> EmbedResult:
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
        # changes. `usage.total_tokens` is the batched input token count.
        ordered = sorted(data["data"], key=lambda d: d["index"])
        usage = data.get("usage") or {}
        return EmbedResult(
            vectors=[np.asarray(d["embedding"], dtype=np.float32) for d in ordered],
            input_tokens=int(usage.get("total_tokens", 0) or 0),
        )


def build_embedder(
    model: str,
    api_token: str | None,
    ollama_host: str,
    dimensions: int,
) -> Embedder:
    """Dispatch on the "<provider>:<model>" prefix in `model`. Two providers
    are currently wired up: `ollama` (local daemon, no auth) and `voyageai`
    (hosted, requires the user's token). Adding a new provider is a new
    class above plus a branch here.

    `api_token` is the decrypted per-user token for whichever provider
    the model string selects; ignored for ollama, required for voyageai.
    """
    provider, model_name = split_model(model)
    if provider == "ollama":
        return OllamaEmbedder(host=ollama_host, model=model_name, dimensions=dimensions)
    if provider == "voyageai":
        if api_token is None:
            raise ValueError("voyageai embedder requires api_token to be set")
        return VoyageEmbedder(
            api_key=api_token, model=model_name, dimensions=dimensions
        )
    raise ValueError(
        f"Unsupported embedding provider '{provider}'. "
        "Wire it up by adding a class above and a branch in build_embedder."
    )
