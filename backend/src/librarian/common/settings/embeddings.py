from pydantic import BaseModel


class EmbeddingsSettings(BaseModel):
    """Embedder-side knobs that are deployment-wide rather than per-user.
    Both processes (api, service) embed with the same model the user
    picked, but everyone embeds at the same `dimensions` and chunks the
    same way — those are properties of the corpus's storage layout.

    `dimensions` MUST match the vector(N) column width in the data_blobs
    schema (currently 1024); changing it requires a migration. Matryoshka-
    capable embedding models truncate server-side to this; non-truncating
    models that don't return this dimensionality surface a clear error at
    INSERT time.
    """

    dimensions: int = 1024

    # Long inputs (especially with large pages_per_blob) routinely exceed
    # an embedder's context limit. We split the embedder input into
    # sub-chunks, embed all in one batched call, then mean + L2-normalise
    # back to one vector per item.
    #
    # `chunk_chars` is the target size — the chunker aims to break at the
    # first whitespace at or after this many characters. `chunk_chars_max`
    # is the absolute ceiling: if no whitespace exists in
    # [target, max), we hard-cut at max rather than producing an
    # unbounded chunk. ~4 chars/token is the rough heuristic, so 4000 ≈
    # 1000 tokens (safe under ollama's default num_ctx); bump both if you
    # raise num_ctx on the ollama side.
    chunk_chars: int = 4000
    chunk_chars_max: int = 5000
