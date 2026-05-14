from fastapi import APIRouter

from app.schemas.queue import QueueHealthResponse
from app.services.queue_health import collect_queue_health

router = APIRouter()


@router.get("/health", response_model=QueueHealthResponse)
def queue_health() -> QueueHealthResponse:
    return collect_queue_health()
