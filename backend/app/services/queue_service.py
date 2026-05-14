from redis import Redis
from rq import Queue

from app.core.config import settings

WORKER_JOB_PATH = "workers.video_worker.process_video_job"


class QueueService:
    """RQ integration: enqueue by import path so workers do not serialize service objects."""

    def __init__(self, redis_url: str | None = None, queue_name: str | None = None) -> None:
        url = redis_url or settings.redis_url
        name = queue_name or settings.queue_name
        self._redis = Redis.from_url(url, decode_responses=False)
        self._queue = Queue(name, connection=self._redis)

    def enqueue_video_processing(self, job_id: str) -> str:
        rq_job = self._queue.enqueue(WORKER_JOB_PATH, job_id)
        return rq_job.id
