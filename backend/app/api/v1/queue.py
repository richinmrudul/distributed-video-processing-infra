from fastapi import APIRouter
from redis import Redis
from rq import Queue
from rq.registry import DeferredJobRegistry, FailedJobRegistry, StartedJobRegistry

from app.core.config import settings
from app.schemas.queue import QueueHealthResponse

router = APIRouter()


@router.get("/health", response_model=QueueHealthResponse)
def queue_health() -> QueueHealthResponse:
    queue_name = settings.queue_name
    try:
        conn = Redis.from_url(settings.redis_url, decode_responses=False)
        conn.ping()
    except Exception as exc:
        return QueueHealthResponse(
            redis_connected=False,
            queue_name=queue_name,
            redis_error=str(exc),
        )

    try:
        queue = Queue(queue_name, connection=conn)
        failed_registry = FailedJobRegistry(queue=queue)
        started_registry = StartedJobRegistry(queue=queue)
        deferred_registry = DeferredJobRegistry(queue=queue)
        return QueueHealthResponse(
            redis_connected=True,
            queue_name=queue_name,
            queued_jobs_count=len(queue),
            failed_jobs_count=len(failed_registry),
            started_jobs_count=len(started_registry),
            deferred_jobs_count=len(deferred_registry),
        )
    except Exception as exc:
        return QueueHealthResponse(
            redis_connected=True,
            queue_name=queue_name,
            redis_error=str(exc),
        )
