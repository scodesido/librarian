from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from librarian.db.table import Table, TableModel

# Closed vocabulary for `operation` — mirrors the DB CHECK in
# 202605290001_user_settings.sql. Adding an operation is a Pydantic +
# migration pair.
Operation = Literal[
    "blob_extract",
    "blob_tag",
    "node_extract_leaf",
    "node_extract_internal",
    "retrieval",
    "extract_search_terms",
    "embed_blob",
    "embed_query",
]


class UserTokenUsageModel(TableModel):
    usage_id: int
    user_id: int
    operation: Operation
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    created_at: datetime


class UsageAggregate(BaseModel):
    """One aggregated bucket over `user_token_usage`. The `(operation,
    provider, model)` triple is the grouping key; sums and counts are
    over rows whose `created_at` lies within the caller-chosen window.
    """

    operation: Operation
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    call_count: int


class UserTokenUsage(Table):
    async def insert(
        self,
        user_id: int,
        operation: Operation,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        await self.conn.execute(
            (
                "INSERT INTO user_token_usage "
                "(user_id, operation, provider, model, input_tokens, output_tokens) "
                "VALUES ($1, $2, $3, $4, $5, $6)"
            ),
            user_id,
            operation,
            provider,
            model,
            input_tokens,
            output_tokens,
        )

    async def aggregate(
        self, user_id: int, since: datetime | None = None
    ) -> list[UsageAggregate]:
        """Per-(operation, provider, model) sums of input/output tokens
        and call counts for `user_id`. `since` limits to rows with
        `created_at >= since`; None aggregates over all-time. Results
        come back ordered by `SUM(input_tokens) DESC` so the heaviest
        consumers float to the top of the FE's usage table.

        Two queries (with/without `since`) rather than one with an
        `OR $2 IS NULL` predicate: the latter defeats the
        `idx_user_token_usage_user_id_created_at` index on the
        windowed path.
        """
        if since is None:
            rows = await self.conn.fetch(
                "SELECT operation, provider, model, "
                "       SUM(input_tokens) AS input_tokens, "
                "       SUM(output_tokens) AS output_tokens, "
                "       COUNT(*) AS call_count "
                "FROM user_token_usage "
                "WHERE user_id = $1 "
                "GROUP BY operation, provider, model "
                "ORDER BY SUM(input_tokens) DESC",
                user_id,
            )
        else:
            rows = await self.conn.fetch(
                "SELECT operation, provider, model, "
                "       SUM(input_tokens) AS input_tokens, "
                "       SUM(output_tokens) AS output_tokens, "
                "       COUNT(*) AS call_count "
                "FROM user_token_usage "
                "WHERE user_id = $1 AND created_at >= $2 "
                "GROUP BY operation, provider, model "
                "ORDER BY SUM(input_tokens) DESC",
                user_id,
                since,
            )
        return [UsageAggregate.model_validate(dict(r)) for r in rows]
