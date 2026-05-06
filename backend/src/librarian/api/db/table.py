from typing import Self

from asyncpg import Record
from asyncpg.pool import PoolConnectionProxy
from pydantic import BaseModel


class TableModel(BaseModel):
    @classmethod
    def from_record(cls, record: Record | None) -> Self | None:
        if record is None:
            return None
        return cls.model_validate(dict(record))


class Table:
    def __init__(self, conn: PoolConnectionProxy[Record]) -> None:
        self.conn = conn
