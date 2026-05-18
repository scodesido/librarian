from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from librarian.db.table import Table, TableModel


class DataNodeWeightsModel(TableModel):
    node_weight_id: int
    user_id: int
    node_id: int
    centroid: NDArray[np.float32]
    blob_count: int
    created_at: datetime

    model_config = {"arbitrary_types_allowed": True}


class DataNodeWeights(Table):
    async def insert(
        self,
        user_id: int,
        node_id: int,
        centroid: NDArray[np.float32],
        blob_count: int,
    ) -> int:
        weight_id: int = await self.conn.fetchval(
            (
                "INSERT INTO data_node_weights "
                "(user_id, node_id, centroid, blob_count) "
                "VALUES ($1, $2, $3, $4) RETURNING node_weight_id"
            ),
            user_id,
            node_id,
            centroid,
            blob_count,
        )
        return weight_id
