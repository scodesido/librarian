from datetime import datetime
from typing import Mapping, Sequence

import numpy as np

from librarian.db.table import Table, TableModel


class NodeEmbeddingsModel(TableModel):
    node_id: int
    field: str
    model_id: str
    embedding: list[float]
    created_at: datetime


class NodeEmbeddings(Table):
    async def bulk_insert(
        self,
        node_id: int,
        model_id: str,
        embeddings_by_field: Mapping[str, Sequence[float]],
    ) -> None:
        if not embeddings_by_field:
            return
        rows = [
            (node_id, field, model_id, np.asarray(vec, dtype=np.float32))
            for field, vec in embeddings_by_field.items()
        ]
        await self.conn.executemany(
            (
                "INSERT INTO node_embeddings "
                "(node_id, field, model_id, embedding) "
                "VALUES ($1, $2, $3, $4)"
            ),
            rows,
        )
