from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import (
    VIDEO_CLEANUP_JOBS_TOTAL,
    VIDEO_CLEANUP_OBJECTS_TOTAL,
    VIDEO_CLEANUP_RUNS_TOTAL,
    refresh_cleanup_candidates_gauge,
)
from app.core.tracing import start_span
from app.db.models import VideoJob, VideoJobStatus
from app.services.object_storage_service import ObjectStorageError, ObjectStorageService

log = get_logger(__name__)


@dataclass(frozen=True)
class CleanupCandidate:
    video_id: str
    status: str
    original_filename: str
    raw_object_key: str | None
    processed_object_key: str | None
    thumbnail_object_key: str | None
    age_seconds: float
    reason: str


@dataclass(frozen=True)
class CleanupFailure:
    video_id: str
    reason: str


@dataclass(frozen=True)
class CleanupResult:
    dry_run: bool
    inspected_count: int
    candidate_count: int
    cleaned_count: int
    failed_count: int
    skipped_count: int
    candidates: list[CleanupCandidate]
    cleaned_job_ids: list[str]
    failures: list[CleanupFailure]


class JobCleanupService:
    def __init__(self, object_storage: ObjectStorageService | None = None) -> None:
        self._object_storage = object_storage or ObjectStorageService()

    def find_cleanup_candidates(
        self,
        db: Session,
        *,
        status_filter: str | None = None,
        limit: int | None = None,
        completed_after_days: int | None = None,
        failed_after_days: int | None = None,
        now: datetime | None = None,
    ) -> list[CleanupCandidate]:
        jobs = self._candidate_jobs(db, status_filter=status_filter, limit=limit)
        candidates = filter_cleanup_candidates(
            jobs,
            now=now or datetime.now(timezone.utc),
            completed_after_days=completed_after_days
            if completed_after_days is not None
            else settings.cleanup_completed_after_days,
            failed_after_days=failed_after_days if failed_after_days is not None else settings.cleanup_failed_after_days,
            batch_size=limit or settings.cleanup_batch_size,
        )
        refresh_cleanup_candidates_gauge(candidates)
        return candidates

    def cleanup(
        self,
        db: Session,
        *,
        dry_run: bool = True,
        limit: int | None = None,
        completed_after_days: int | None = None,
        failed_after_days: int | None = None,
        delete_db_rows: bool | None = None,
    ) -> CleanupResult:
        with start_span("app.job_cleanup", "job_cleanup_run", attributes={"cleanup.dry_run": dry_run}) as span:
            if not settings.cleanup_enabled:
                VIDEO_CLEANUP_RUNS_TOTAL.labels(outcome="skipped").inc()
                return CleanupResult(
                    dry_run=dry_run,
                    inspected_count=0,
                    candidate_count=0,
                    cleaned_count=0,
                    failed_count=0,
                    skipped_count=0,
                    candidates=[],
                    cleaned_job_ids=[],
                    failures=[],
                )

            effective_limit = limit or settings.cleanup_batch_size
            jobs = self._candidate_jobs(db, status_filter=None, limit=effective_limit)
            candidates = filter_cleanup_candidates(
                jobs,
                now=datetime.now(timezone.utc),
                completed_after_days=completed_after_days
                if completed_after_days is not None
                else settings.cleanup_completed_after_days,
                failed_after_days=failed_after_days if failed_after_days is not None else settings.cleanup_failed_after_days,
                batch_size=effective_limit,
            )
            refresh_cleanup_candidates_gauge(candidates)
            span.set_attribute("cleanup.candidate_count", len(candidates))
            log.info("cleanup_started", dry_run=dry_run, candidate_count=len(candidates), limit=effective_limit)

            if dry_run:
                VIDEO_CLEANUP_RUNS_TOTAL.labels(outcome="dry_run").inc()
                for candidate in candidates:
                    VIDEO_CLEANUP_JOBS_TOTAL.labels(outcome="dry_run", status=candidate.status).inc()
                log.info("cleanup_finished", dry_run=True, candidate_count=len(candidates), cleaned_count=0, failed_count=0)
                return CleanupResult(
                    dry_run=True,
                    inspected_count=len(jobs),
                    candidate_count=len(candidates),
                    cleaned_count=0,
                    failed_count=0,
                    skipped_count=0,
                    candidates=candidates,
                    cleaned_job_ids=[],
                    failures=[],
                )

            cleaned_ids: list[str] = []
            failures: list[CleanupFailure] = []
            delete_rows = settings.cleanup_delete_db_rows if delete_db_rows is None else delete_db_rows
            by_id = {job.id: job for job in jobs}

            for candidate in candidates:
                job = by_id.get(candidate.video_id)
                if job is None:
                    failures.append(CleanupFailure(video_id=candidate.video_id, reason="job_not_found"))
                    VIDEO_CLEANUP_JOBS_TOTAL.labels(outcome="failed", status=candidate.status).inc()
                    continue
                try:
                    self._cleanup_one(db, job, delete_db_rows=delete_rows)
                except Exception as exc:
                    failures.append(CleanupFailure(video_id=candidate.video_id, reason=str(exc)))
                    job.cleanup_error_message = str(exc)[:8000]
                    db.commit()
                    VIDEO_CLEANUP_JOBS_TOTAL.labels(outcome="failed", status=candidate.status).inc()
                    log.warning("cleanup_job_failed", video_id=candidate.video_id, error=str(exc))
                    continue
                cleaned_ids.append(candidate.video_id)
                VIDEO_CLEANUP_JOBS_TOTAL.labels(outcome="success", status=candidate.status).inc()

            outcome = "success" if not failures else "failed"
            VIDEO_CLEANUP_RUNS_TOTAL.labels(outcome=outcome).inc()
            log.info(
                "cleanup_finished",
                dry_run=False,
                candidate_count=len(candidates),
                cleaned_count=len(cleaned_ids),
                failed_count=len(failures),
            )
            return CleanupResult(
                dry_run=False,
                inspected_count=len(jobs),
                candidate_count=len(candidates),
                cleaned_count=len(cleaned_ids),
                failed_count=len(failures),
                skipped_count=0,
                candidates=candidates,
                cleaned_job_ids=cleaned_ids,
                failures=failures,
            )

    def _candidate_jobs(self, db: Session, *, status_filter: str | None, limit: int | None) -> list[VideoJob]:
        stmt = select(VideoJob).where(
            VideoJob.cleaned_up_at.is_(None),
            or_(VideoJob.status == VideoJobStatus.COMPLETED, VideoJob.status == VideoJobStatus.FAILED),
        )
        if status_filter:
            normalized = status_filter.strip().upper()
            if normalized in ("COMPLETED", "FAILED"):
                stmt = stmt.where(VideoJob.status == VideoJobStatus(normalized))
        stmt = stmt.order_by(VideoJob.updated_at.asc()).limit(limit or settings.cleanup_batch_size)
        return list(db.execute(stmt).scalars().all())

    def _cleanup_one(self, db: Session, job: VideoJob, *, delete_db_rows: bool) -> None:
        status = status_value(job)
        for bucket, key in object_references(job):
            if not key:
                continue
            try:
                self._object_storage.delete_object(bucket, key)
            except ObjectStorageError:
                VIDEO_CLEANUP_OBJECTS_TOTAL.labels(bucket=bucket, outcome="failed").inc()
                raise
            VIDEO_CLEANUP_OBJECTS_TOTAL.labels(bucket=bucket, outcome="success").inc()
            log.info("cleanup_object_deleted", video_id=job.id, bucket=bucket)

        if delete_db_rows:
            db.delete(job)
            db.commit()
            log.info("cleanup_job_deleted", video_id=job.id, status=status)
            return

        job.cleaned_up_at = datetime.now(timezone.utc)
        job.cleanup_error_message = None
        job.raw_object_key = None
        job.processed_object_key = None
        job.thumbnail_object_key = None
        job.raw_path = None
        job.processed_path = None
        job.thumbnail_path = None
        db.commit()
        db.refresh(job)
        log.info("cleanup_job_marked_cleaned", video_id=job.id, status=status)


def status_value(job: Any) -> str:
    status = getattr(job, "status", "")
    return status.value if hasattr(status, "value") else str(status)


def job_age_seconds(job: Any, now: datetime) -> float:
    reference = cleanup_reference_time(job)
    if reference is None:
        reference = getattr(job, "updated_at", None) or getattr(job, "created_at", now)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return max(0.0, (now - reference).total_seconds())


def cleanup_reference_time(job: Any) -> datetime | None:
    status = status_value(job)
    if status == "COMPLETED":
        return getattr(job, "processing_completed_at", None) or getattr(job, "updated_at", None)
    if status == "FAILED":
        return getattr(job, "failed_at", None) or getattr(job, "updated_at", None)
    return None


def is_cleanup_candidate(
    job: Any,
    *,
    now: datetime,
    completed_after_days: int,
    failed_after_days: int,
) -> bool:
    if getattr(job, "cleaned_up_at", None) is not None:
        return False

    status = status_value(job)
    reference = cleanup_reference_time(job)
    if reference is None:
        return False
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)

    if status == "COMPLETED":
        return reference <= now - timedelta(days=completed_after_days)
    if status == "FAILED":
        return bool(getattr(job, "retry_exhausted", False)) and reference <= now - timedelta(days=failed_after_days)
    return False


def candidate_reason(job: Any) -> str:
    status = status_value(job)
    if status == "COMPLETED":
        return "completed_retention_expired"
    if status == "FAILED":
        return "failed_retention_expired"
    return "not_cleanup_candidate"


def object_references(job: Any) -> list[tuple[str, str | None]]:
    return [
        (settings.raw_video_bucket, getattr(job, "raw_object_key", None)),
        (settings.processed_video_bucket, getattr(job, "processed_object_key", None)),
        (settings.thumbnail_bucket, getattr(job, "thumbnail_object_key", None)),
    ]


def to_candidate(job: Any, now: datetime) -> CleanupCandidate:
    return CleanupCandidate(
        video_id=job.id,
        status=status_value(job),
        original_filename=job.original_filename,
        raw_object_key=getattr(job, "raw_object_key", None),
        processed_object_key=getattr(job, "processed_object_key", None),
        thumbnail_object_key=getattr(job, "thumbnail_object_key", None),
        age_seconds=job_age_seconds(job, now),
        reason=candidate_reason(job),
    )


def filter_cleanup_candidates(
    jobs: list[Any],
    *,
    now: datetime,
    completed_after_days: int,
    failed_after_days: int,
    batch_size: int,
) -> list[CleanupCandidate]:
    candidates = [
        to_candidate(job, now)
        for job in jobs
        if is_cleanup_candidate(
            job,
            now=now,
            completed_after_days=completed_after_days,
            failed_after_days=failed_after_days,
        )
    ]
    return candidates[: max(0, batch_size)]
