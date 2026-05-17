from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import STUCK_JOBS_RECOVERED_TOTAL, refresh_stuck_jobs_gauge
from app.core.tracing import start_span
from app.db.models import VideoJob, VideoJobStatus
from app.schemas.jobs import RecoveryResultResponse, StuckJobResponse
from app.services.queue_service import QueueService

log = get_logger(__name__)


class JobRecoveryService:
    def __init__(self, queue: QueueService | None = None) -> None:
        self._queue = queue or QueueService()

    def find_stuck_jobs(self, db: Session) -> list[StuckJobResponse]:
        with start_span("app.job_recovery", "find_stuck_jobs") as span:
            now = datetime.now(timezone.utc)
            jobs = list(
                db.execute(
                    select(VideoJob).where(
                        or_(
                            VideoJob.status == VideoJobStatus.PROCESSING,
                            VideoJob.status == VideoJobStatus.QUEUED,
                        )
                    )
                )
                .scalars()
                .all()
            )
            stuck = [item for job in jobs if (item := self._stuck_response(job, now)) is not None]
            refresh_stuck_jobs_gauge(stuck)
            span.set_attribute("stuck.count", len(stuck))
            return stuck

    def recover_stuck_jobs(self, db: Session) -> RecoveryResultResponse:
        with start_span("app.job_recovery", "recover_stuck_jobs") as span:
            stuck_jobs = self.find_stuck_jobs(db)
            recovered_ids: list[str] = []
            failed_ids: list[str] = []
            skipped_ids: list[str] = []

            for stuck in stuck_jobs:
                job = db.get(VideoJob, stuck.id)
                if job is None:
                    skipped_ids.append(stuck.id)
                    STUCK_JOBS_RECOVERED_TOTAL.labels(
                        original_status=stuck.status.value if hasattr(stuck.status, "value") else str(stuck.status),
                        outcome="skipped",
                    ).inc()
                    continue
                outcome = self._recover_one(db, job)
                if outcome == "requeued":
                    recovered_ids.append(job.id)
                elif outcome in ("failed", "enqueue_failed"):
                    failed_ids.append(job.id)
                else:
                    skipped_ids.append(job.id)

            refreshed = self.find_stuck_jobs(db)
            refresh_stuck_jobs_gauge(refreshed)
            result = RecoveryResultResponse(
                inspected_count=len(stuck_jobs),
                recovered_count=len(recovered_ids),
                failed_count=len(failed_ids),
                skipped_count=len(skipped_ids),
                recovered_job_ids=recovered_ids,
                failed_job_ids=failed_ids,
                skipped_job_ids=skipped_ids,
            )
            span.set_attribute("stuck.count", result.inspected_count)
            span.set_attribute("recovered.count", result.recovered_count)
            span.set_attribute("failed.count", result.failed_count)
            return result

    def _stuck_response(self, job: VideoJob, now: datetime) -> StuckJobResponse | None:
        if job.status == VideoJobStatus.PROCESSING:
            if job.processing_started_at is None:
                return None
            age = _age_seconds(now, job.processing_started_at)
            if age <= settings.stuck_processing_timeout_seconds:
                return None
            reason = "processing_timeout"
        elif job.status == VideoJobStatus.QUEUED:
            age = _age_seconds(now, job.updated_at)
            if age <= settings.stuck_queued_timeout_seconds:
                return None
            reason = "queued_timeout"
        else:
            return None

        return StuckJobResponse(
            id=job.id,
            status=job.status,
            original_filename=job.original_filename,
            storage_backend=job.storage_backend,
            queue_job_id=job.queue_job_id,
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
            retry_exhausted=job.retry_exhausted,
            processing_started_at=job.processing_started_at,
            created_at=job.created_at,
            updated_at=job.updated_at,
            age_seconds=age,
            stuck_reason=reason,
        )

    def _recover_one(self, db: Session, job: VideoJob) -> str:
        original_status = job.status.value if hasattr(job.status, "value") else str(job.status)
        with start_span(
            "app.job_recovery",
            "recover_single_stuck_job",
            attributes={"job.status": original_status},
        ) as span:
            if job.status not in (VideoJobStatus.PROCESSING, VideoJobStatus.QUEUED):
                outcome = "skipped"
                STUCK_JOBS_RECOVERED_TOTAL.labels(original_status=original_status, outcome=outcome).inc()
                span.set_attribute("recovery.outcome", outcome)
                return outcome

            if job.attempt_count >= job.max_attempts:
                self._mark_failed(db, job, "Job exceeded processing timeout and retry limit")
                outcome = "failed"
                STUCK_JOBS_RECOVERED_TOTAL.labels(original_status=original_status, outcome=outcome).inc()
                span.set_attribute("recovery.outcome", outcome)
                return outcome

            try:
                rq_job_id = self._queue.enqueue_video_processing(job.id, max_attempts=job.max_attempts)
            except Exception as exc:
                log.exception("stuck_job_recovery_enqueue_failed", video_id=job.id)
                self._mark_failed(db, job, f"recovery_enqueue_failed: {exc}")
                outcome = "enqueue_failed"
                STUCK_JOBS_RECOVERED_TOTAL.labels(original_status=original_status, outcome=outcome).inc()
                span.set_attribute("recovery.outcome", outcome)
                return outcome

            self._reset_for_requeue(job)
            job.queue_job_id = rq_job_id
            db.commit()
            db.refresh(job)
            outcome = "requeued"
            STUCK_JOBS_RECOVERED_TOTAL.labels(original_status=original_status, outcome=outcome).inc()
            span.set_attribute("recovery.outcome", outcome)
            return outcome

    def _reset_for_requeue(self, job: VideoJob) -> None:
        job.status = VideoJobStatus.QUEUED
        job.error_message = None
        job.failed_at = None
        job.last_error_type = None
        job.retry_exhausted = False
        job.processing_started_at = None
        job.processing_completed_at = None
        job.processing_duration_seconds = None
        job.processed_path = None
        job.thumbnail_path = None
        job.processed_object_key = None
        job.thumbnail_object_key = None

    def _mark_failed(self, db: Session, job: VideoJob, message: str) -> None:
        now = datetime.now(timezone.utc)
        job.status = VideoJobStatus.FAILED
        job.retry_exhausted = True
        job.failed_at = now
        job.processing_completed_at = now
        job.last_error_type = "StuckJobTimeout"
        job.error_message = message[:8000]
        db.commit()
        db.refresh(job)


def _age_seconds(now: datetime, then: datetime) -> float:
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return max(0.0, (now - then).total_seconds())
