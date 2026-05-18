import numpy as np
from aiohttp import ClientSession
from numpy.typing import NDArray

from librarian.service.abstract import RollingAbstract
from librarian.service.blob_extractor.settings import BlobExtractorSettings
from librarian.service.embedder import Embedder, OllamaEmbedder, VoyageEmbedder


def build_embedder(settings: BlobExtractorSettings) -> Embedder:
    """Dispatch on the "<provider>:<model>" prefix in
    settings.embedding_model. Two providers are currently wired up:
    `ollama` (local daemon) and `voyageai` (hosted). Adding a new
    provider is a new branch here plus a small class in
    `service/embedder.py`.
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
            api_key=settings.get_voyage_api_key,
            model=model_name,
            dimensions=settings.embedding_dimensions,
        )
    raise ValueError(
        f"Unsupported embedding provider '{provider_name}'. "
        "Wire it up in service/embedder.py and add a branch in build_embedder."
    )


def serialize_abstract_for_embed(abstract: RollingAbstract) -> str:
    """Compose the RollingAbstract fields that carry semantic prose into a single
    string. The categorical fields (intended_audience, content_type, domains)
    are short labels and not included; they're more useful as JSONB filters.
    """
    return (
        f"{abstract.summary}\n{', '.join(abstract.topics)}\n{abstract.running_summary}"
    )


def normalize_l2(vec: NDArray[np.float32]) -> NDArray[np.float32]:
    norm = float(np.linalg.norm(vec))
    if norm == 0.0:
        return vec
    return (vec / norm).astype(np.float32)


async def embed_blobs(
    http: ClientSession,
    embedder: Embedder,
    raw_texts: list[str],
    abstracts: list[RollingAbstract],
) -> list[NDArray[np.float32]]:
    """One batched call; returns one L2-unit vector per (raw_text, abstract).
    The embedder input is `raw_text + "\\n\\n" + serialize_abstract_for_embed`.
    """
    if len(raw_texts) != len(abstracts):
        raise ValueError(
            f"raw_texts ({len(raw_texts)}) and abstracts ({len(abstracts)}) "
            "must have the same length"
        )
    if not raw_texts:
        return []
    inputs = [
        f"{raw}\n\n{serialize_abstract_for_embed(abstract)}"
        for raw, abstract in zip(raw_texts, abstracts, strict=True)
    ]
    embeddings = await embedder.embed_documents(http, inputs)
    return [normalize_l2(e) for e in embeddings]


def compute_with_file_embeddings(
    embedding_blobs: list[NDArray[np.float32]],
) -> list[NDArray[np.float32]]:
    """`file_embedding = normalize(sum(embedding_blobs))`; then per blob
    `embedding_with_file[i] = normalize(embedding_blobs[i] + file_embedding)`.
    """
    if not embedding_blobs:
        return []
    file_embedding = normalize_l2(np.sum(embedding_blobs, axis=0).astype(np.float32))
    return [normalize_l2(eb + file_embedding) for eb in embedding_blobs]
