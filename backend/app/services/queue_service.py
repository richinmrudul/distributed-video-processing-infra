from redis import Redis
from rq import Queue
from rq.job import Retry

from app.core.config import settings

WORKER_JOB_PATH = "workers.video_worker.process_video_job"

# Align RQ retries with VideoJob.max_attempts: one initial run + (max_attempts - 1) RQ retries.
# interval > 0 schedules jobs in DeferredJobRegistry; without rq-scheduler they are not
# re-run at the scheduled time. Use immediate retries so workers pick them up reliably.
RQ_RETRY_INTERVAL_SECONDS = 0


class QueueService:
    """RQ integration: enqueue by import path so workers do not serialize service objects."""

    def __init__(self, redis_url: str | None = None, queue_name: str | None = None) -> None:
        url = redis_url or settings.redis_url
        name = queue_name or settings.queue_name
        self._redis = Redis.from_url(url, decode_responses=False)
        self._queue = Queue(name, connection=self._redis)

    def enqueue_video_processing(self, video_job_id: str, *, max_attempts: int) -> str:
        rq_max_retries = max(0, max_attempts - 1)
        retry = (
            Retry(max=rq_max_retries, interval=RQ_RETRY_INTERVAL_SECONDS)
            if rq_max_retries
            else None
        )
        rq_job = self._queue.enqueue(
            WORKER_JOB_PATH,
            video_job_id,
            job_timeout=settings.rq_job_timeout_seconds,
            retry=retry,
        )
        return rq_job.id
