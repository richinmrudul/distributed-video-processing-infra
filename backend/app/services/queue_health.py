"""Collect RQ + Redis queue metrics for the API health endpoint."""

from datetime import datetime, timezone

from redis import Redis
from rq import Queue
from rq.job import Job
from rq.registry import DeferredJobRegistry, FailedJobRegistry, FinishedJobRegistry, StartedJobRegistry
from rq.worker_registration import get_keys

from app.core.config import settings
from app.schemas.queue import QueueHealthResponse, QueuePressureLevel


def _queue_pressure(queued: int) -> QueuePressureLevel:
    if queued <= 5:
        return QueuePressureLevel.LOW
    if queued <= 20:
        return QueuePressureLevel.MEDIUM
    return QueuePressureLevel.HIGH


def _estimate_queue_latency_seconds(queue: Queue) -> float | None:
    ids = queue.get_job_ids(0, 1)
    if not ids:
        return None
    try:
        job = Job.fetch(ids[0], connection=queue.connection)
    except Exception:
        return None
    if job.enqueued_at is None:
        return None
    now = datetime.now(timezone.utc)
    enq = job.enqueued_at
    if enq.tzinfo is None:
        enq = enq.replace(tzinfo=timezone.utc)
    return max(0.0, (now - enq).total_seconds())


def collect_queue_health() -> QueueHealthResponse:
    queue_name = settings.queue_name
    conn = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        conn.ping()
    except Exception as exc:
        conn.close()
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
        finished_registry = FinishedJobRegistry(queue=queue)
        worker_keys = get_keys(queue)
        worker_names = sorted(
            (k.decode() if isinstance(k, bytes) else str(k) for k in worker_keys),
            key=str,
        )
        queued = len(queue)
        latency = _estimate_queue_latency_seconds(queue)
        active = len(started_registry)
        return QueueHealthResponse(
            redis_connected=True,
            queue_name=queue_name,
            queued_jobs_count=queued,
            failed_jobs_count=len(failed_registry),
            started_jobs_count=active,
            deferred_jobs_count=len(deferred_registry),
            finished_jobs_count=len(finished_registry),
            active_jobs_count=active,
            worker_count=len(worker_names),
            worker_names=worker_names[:50],
            queue_latency_estimate_seconds=latency,
            queue_pressure_level=_queue_pressure(queued),
        )
    except Exception as exc:
        return QueueHealthResponse(
            redis_connected=True,
            queue_name=queue_name,
            redis_error=str(exc),
        )
    finally:
        conn.close()
