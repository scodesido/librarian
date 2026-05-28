import numpy as np
from aiohttp import ClientSession
from numpy.typing import NDArray

from librarian.api.settings import QuerySettings
from librarian.service.embedder import (
    Embedder,
    OllamaEmbedder,
    VoyageEmbedder,
    chunk_for_embedding,
    normalize_l2,
)


def build_query_embedder(settings: QuerySettings) -> Embedder:
    """Dispatch on the "<provider>:<model>" prefix in
    settings.embedding_model. Same two providers as blob_extractor's
    builder; kept separate so the API can be configured independently
    in YAML (and so the QuerySettings surface doesn't depend on the
    blob_extractor module).
    """
    provider_name, model_name = settings.embedding_model.split(":", 1)
    if provider_name == "ollama":
        return OllamaEmbedder(
            host=settings.ollama_host,
            model=model_name,
            dimensions=settings.embedding_dimensions,
        )
    if provider_name == "voyageai":
        return VoyageEmbedder(
            api_key=settings.get_embedder_api_token,
            model=model_name,
            dimensions=settings.embedding_dimensions,
        )
    raise ValueError(
        f"Unsupported embedding provider '{provider_name}'. "
        "Wire it up in service/embedder.py and add a branch in build_query_embedder."
    )


async def embed_search_terms(
    http: ClientSession,
    embedder: Embedder,
    text: str,
    chunk_chars: int,
    chunk_chars_max: int,
) -> NDArray[np.float32]:
    """Embed the user's search terms into a single L2-unit vector,
    using the same chunk-then-mean-pool path that blob_extractor uses
    for raw text. Short search strings yield a single chunk; the helper
    is here so unusual long inputs don't blow past the embedder's
    context limit silently.

    Voyage's API distinguishes `input_type="document"` vs `"query"`;
    we currently call `embed_documents` for both indexing and querying
    so the spaces match exactly. Adding an `embed_queries` variant is
    a future change motivated by retrieval quality, not by this feature.
    """
    chunks = chunk_for_embedding(text, chunk_chars, chunk_chars_max)
    vecs = await embedder.embed_documents(http, chunks)
    return normalize_l2(np.mean(np.stack(vecs), axis=0).astype(np.float32))
