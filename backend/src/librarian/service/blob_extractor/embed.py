import numpy as np
from aiohttp import ClientSession
from numpy.typing import NDArray

from librarian.service.abstract import RollingAbstract
from librarian.service.blob_extractor.settings import BlobExtractorSettings
from librarian.service.embedder import (
    Embedder,
    OllamaEmbedder,
    VoyageEmbedder,
    chunk_for_embedding,
    normalize_l2,
)


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
    string. The pure-label fields (persons, organizations, works,
    other_entities, locations, language) are kept out — they're more useful as
    JSONB filters than as similarity anchors. Empty list/string fields are
    skipped so they don't introduce stray separators.

    `content_tags` and `format_tags` ARE included even though they're
    short closed-vocabulary labels: shared tags pull tag-similar blobs
    together during `tree_builder` descent, which tightens the
    set-unions at internal nodes. The redundancy with `topics`/`domains`
    is by design.
    """
    parts: list[str] = [
        abstract.title,
        abstract.summary,
        abstract.intended_audience,
        ", ".join(abstract.topics),
        ", ".join(abstract.domains),
        ", ".join(abstract.content_tags),
        ", ".join(abstract.format_tags),
        ", ".join(abstract.time_period),
        "\n".join(abstract.key_questions),
        "\n".join(abstract.key_claims),
        abstract.running_summary,
    ]
    return "\n".join(p for p in parts if p)


async def embed_blobs(
    http: ClientSession,
    embedder: Embedder,
    raw_texts: list[str],
    abstracts: list[RollingAbstract],
    chunk_chars: int,
    chunk_chars_max: int,
) -> list[NDArray[np.float32]]:
    """Returns one L2-unit vector per (raw_text, abstract) pair.

    For each blob the raw text and the serialized abstract are embedded
    as two independent streams: each stream is split into sub-chunks
    bounded by `chunk_chars_max` (so we stay under the embedder's
    context limit), all sub-chunks across both streams and all blobs
    go through a single batched embedder call, then per-blob per-stream
    we mean-pool and L2-normalise to get `raw_vec` and `abstract_vec`.

    The blob vector is `normalize(raw_vec + abstract_vec)` when raw
    text is non-empty (after `.strip()`); when the raw text is empty
    or whitespace-only — e.g. an image-only PDF chunk where pypdf
    extracted nothing — the blob vector is just `abstract_vec`, so
    the embedding doesn't get polluted by a degenerate empty-string
    encoding. Embedding the abstract as its own stream gives it the
    same weight as the raw text regardless of raw length, which is
    the point: the abstract carries the librarian-style classification
    that node-level rollups reuse.
    """
    if len(raw_texts) != len(abstracts):
        raise ValueError(
            f"raw_texts ({len(raw_texts)}) and abstracts ({len(abstracts)}) "
            "must have the same length"
        )
    if not raw_texts:
        return []
    abstract_texts = [serialize_abstract_for_embed(a) for a in abstracts]
    # Track each sub-chunk's origin as (blob_idx, kind) where kind is
    # "raw" or "abstract". Empty/whitespace raw streams are skipped so
    # they don't pollute the average; an empty abstract is treated as
    # a bug (every blob has a valid Abstract by construction).
    all_chunks: list[str] = []
    origin: list[tuple[int, str]] = []
    for i, raw in enumerate(raw_texts):
        if not raw.strip():
            continue
        for c in chunk_for_embedding(raw, chunk_chars, chunk_chars_max):
            all_chunks.append(c)
            origin.append((i, "raw"))
    for i, abs_text in enumerate(abstract_texts):
        if not abs_text:
            raise ValueError(
                f"blob {i} produced an empty serialized abstract; the "
                "abstract is required for the blob embedding"
            )
        for c in chunk_for_embedding(abs_text, chunk_chars, chunk_chars_max):
            all_chunks.append(c)
            origin.append((i, "abstract"))
    embeddings = await embedder.embed_documents(http, all_chunks)
    raw_groups: list[list[NDArray[np.float32]]] = [[] for _ in raw_texts]
    abs_groups: list[list[NDArray[np.float32]]] = [[] for _ in raw_texts]
    for (i, kind), vec in zip(origin, embeddings, strict=True):
        (raw_groups if kind == "raw" else abs_groups)[i].append(vec)
    result: list[NDArray[np.float32]] = []
    for raw_g, abs_g in zip(raw_groups, abs_groups, strict=True):
        abs_vec = normalize_l2(np.mean(np.stack(abs_g), axis=0).astype(np.float32))
        if not raw_g:
            result.append(abs_vec)
            continue
        raw_vec = normalize_l2(np.mean(np.stack(raw_g), axis=0).astype(np.float32))
        result.append(normalize_l2((raw_vec + abs_vec).astype(np.float32)))
    return result


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
