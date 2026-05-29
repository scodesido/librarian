from dataclasses import dataclass
from typing import Any

from asyncpg.pool import PoolConnectionProxy

from librarian.common.settings.model_catalog import split_model
from librarian.db.tables.user_token_usage import Operation, UserTokenUsage


@dataclass(frozen=True)
class TokenUsage:
    """Per-call input/output token count. Returned by every helper that
    fronts an LLM/embedder call; the orchestrator (process_file,
    process_one_node, preflight_query, run_retrieval) writes one row to
    `user_token_usage` per record via `record_usage` below.

    Embedders carry `output_tokens=0` by convention — they consume input,
    produce vectors, and don't have an LLM-style "output text" tokens
    notion. Providers that don't surface token counts at all (a
    hypothetical future one) yield zeros and the ledger row records the
    fact that the call happened, just with empty cost.
    """

    input_tokens: int
    output_tokens: int


def agent_usage(result: Any) -> TokenUsage:
    """Extract `(input_tokens, output_tokens)` from a pydantic-ai
    `RunResult`. The SDK exposes `result.usage()` returning a `RunUsage`
    object whose `input_tokens` / `output_tokens` fields may be `None`
    if the provider didn't report them (some local providers leave them
    unset). We coerce missing fields to 0 so the ledger row always
    carries non-negative integers — the DB CHECK requires this.

    Typed as `Any` because pydantic-ai's RunResult is generic and the
    concrete type varies per call site; the only attribute we rely on
    is `usage()`, which every RunResult exposes.
    """
    usage = result.usage()
    input_tokens = getattr(usage, "input_tokens", 0)
    output_tokens = getattr(usage, "output_tokens", 0)
    return TokenUsage(
        input_tokens=int(input_tokens or 0),
        output_tokens=int(output_tokens or 0),
    )


async def record_usage(
    conn: PoolConnectionProxy,
    user_id: int,
    operation: Operation,
    model: str,
    usage: TokenUsage,
) -> None:
    """Append one row to `user_token_usage`. `provider` is derived from
    the "<provider>:<model>" prefix; the full `model` string is stored
    verbatim so historical rows survive catalog edits that change a
    model's label (or drop a model entirely).

    Workers call this inside their per-iteration transaction so a
    rollback unwinds the ledger row alongside the work. Retrieval calls
    it outside any transaction — the writes are eventually-consistent
    with the agent's behaviour, which is the right tradeoff for a
    query-time API path that already runs partly in an SSE generator
    outliving the request scope.
    """
    provider, _ = split_model(model)
    await UserTokenUsage(conn).insert(
        user_id=user_id,
        operation=operation,
        provider=provider,
        model=model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
    )
