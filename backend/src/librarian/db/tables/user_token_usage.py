from datetime import datetime
from typing import Literal

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
