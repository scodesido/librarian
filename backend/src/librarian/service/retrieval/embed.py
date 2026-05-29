import numpy as np
from aiohttp import ClientSession
from numpy.typing import NDArray

from librarian.service.embedder import (
    Embedder,
    chunk_for_embedding,
    normalize_l2,
)


async def embed_search_terms(
    http: ClientSession,
    embedder: Embedder,
    text: str,
    chunk_chars: int,
    chunk_chars_max: int,
) -> tuple[NDArray[np.float32], int]:
    """Embed the user's search terms into a single L2-unit vector, plus
    the provider-reported input token count for the call (0 if the
    provider doesn't surface one). Uses the same chunk-then-mean-pool
    path that blob_extractor uses for raw text. Short search strings
    yield a single chunk; the helper is here so unusual long inputs
    don't blow past the embedder's context limit silently.

    Voyage's API distinguishes `input_type="document"` vs `"query"`;
    we currently call `embed_documents` for both indexing and querying
    so the spaces match exactly. Adding an `embed_queries` variant is
    a future change motivated by retrieval quality, not by this feature.
    """
    chunks = chunk_for_embedding(text, chunk_chars, chunk_chars_max)
    embed_result = await embedder.embed_documents(http, chunks)
    vec = normalize_l2(
        np.mean(np.stack(embed_result.vectors), axis=0).astype(np.float32)
    )
    return vec, embed_result.input_tokens
