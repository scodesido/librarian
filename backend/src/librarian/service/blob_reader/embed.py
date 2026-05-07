from typing import Any

from pydantic_ai import Embedder
from pydantic_ai.embeddings.voyageai import VoyageAIEmbeddingModel
from pydantic_ai.providers.voyageai import VoyageAIProvider

from librarian.service.blob_reader.abstract import Abstract
from librarian.service.blob_reader.settings import BlobReaderSettings


def build_embedder(settings: BlobReaderSettings) -> Embedder:
    provider_name, model_name = settings.embedding_model.split(":", 1)
    if provider_name != "voyageai":
        raise ValueError(
            f"Unsupported embedding provider '{provider_name}'. "
            "Only 'voyageai' is wired up; extend build_embedder to add more."
        )
    model = VoyageAIEmbeddingModel(
        model_name,
        provider=VoyageAIProvider(api_key=settings.get_voyage_api_key),
    )
    return Embedder(model)


def field_to_text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


async def embed_abstracts(
    embedder: Embedder,
    abstracts: list[Abstract],
    fields: list[str],
) -> list[dict[str, list[float]]]:
    if not abstracts or not fields:
        return [{} for _ in abstracts]
    inputs: list[str] = []
    for abstract in abstracts:
        for field in fields:
            inputs.append(field_to_text(getattr(abstract, field)))
    result = await embedder.embed_documents(inputs)
    n_fields = len(fields)
    return [
        {
            field: list(result.embeddings[i * n_fields + j])
            for j, field in enumerate(fields)
        }
        for i in range(len(abstracts))
    ]
