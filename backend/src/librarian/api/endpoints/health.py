from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/health")


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


@router.get("/", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse()
