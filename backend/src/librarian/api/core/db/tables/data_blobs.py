from datetime import datetime

from librarian.api.core.db.table import Table, TableModel


class DataBlobsModel(TableModel):
    blob_id: int
    file_id: int
    start: int
    end: int
    created_at: datetime
    updated_at: datetime


class DataBlobs(Table):
    pass
