from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.metrics import MANUAL_RETRIES_TOTAL
from app.db.models import VideoJob, VideoJobStatus
from app.services.queue_service import QueueService

log = get_logger(__name__)


class JobService:
    def __init__(self, queue: QueueService | None = None) -> None:
        self._queue = queue or QueueService()

    def list_failed_jobs(
        self,
        db: Session,
        *,
        limit: int = 20,
        retry_exhausted: bool | None = None,
    ) -> list[VideoJob]:
        stmt = (
            select(VideoJob)
            .where(VideoJob.status == VideoJobStatus.FAILED)
            .order_by(VideoJob.failed_at.desc().nullslast(), VideoJob.updated_at.desc())
            .limit(limit)
        )
        if retry_exhausted is not None:
            stmt = stmt.where(VideoJob.retry_exhausted == retry_exhausted)
        return list(db.execute(stmt).scalars().all())

    def retry_failed_job(self, db: Session, video_id: str) -> VideoJob:
        vid = video_id.strip()
        job = db.get(VideoJob, vid)
        if job is None:
            raise JobNotFoundError(vid)

        if job.status == VideoJobStatus.COMPLETED:
            raise JobRetryConflictError("Job already completed")
        if job.status in (VideoJobStatus.PROCESSING, VideoJobStatus.QUEUED):
            raise JobRetryConflictError(f"Job is currently {job.status.value}")
        if job.status != VideoJobStatus.FAILED:
            raise JobRetryConflictError(f"Job status {job.status.value} is not retryable")

        try:
            rq_job_id = self._queue.enqueue_video_processing(job.id, max_attempts=job.max_attempts)
        except Exception as exc:
            log.exception("manual_retry_enqueue_failed", video_id=vid)
            raise JobEnqueueError(str(exc)) from exc

        now = datetime.now(timezone.utc)
        job.status = VideoJobStatus.QUEUED
        job.error_message = None
        job.failed_at = None
        job.last_error_type = None
        job.retry_exhausted = False
        job.attempt_count = 0
        job.processing_started_at = None
        job.processing_completed_at = None
        job.processing_duration_seconds = None
        job.processed_path = None
        job.thumbnail_path = None
        job.processed_object_key = None
        job.thumbnail_object_key = None
        job.manual_retry_count += 1
        job.manually_retried_at = now
        job.queue_job_id = rq_job_id
        db.commit()
        db.refresh(job)

        backend = job.storage_backend or "local"
        MANUAL_RETRIES_TOTAL.labels(storage_backend=backend).inc()
        log.info(
            "manual_retry_enqueued",
            video_id=vid,
            queue_job_id=rq_job_id,
            manual_retry_count=job.manual_retry_count,
        )
        return job


class JobNotFoundError(Exception):
    pass


class JobRetryConflictError(Exception):
    pass


class JobEnqueueError(Exception):
    pass
