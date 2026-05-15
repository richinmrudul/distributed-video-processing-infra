"""RQ worker entrypoint: FFmpeg runs here, not in the API process.

Worker metrics use the default prometheus_client registry in each worker process.
They are incremented locally but are NOT exposed on HTTP unless a scrape endpoint is added later.
Prometheus in docker-compose currently scrapes only the API /metrics endpoint.
"""

import os
import socket
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.metrics import (
    VIDEO_PROCESSING_DURATION_SECONDS,
    VIDEO_PROCESSING_FAILURES_TOTAL,
    VIDEO_PROCESSING_JOBS_TOTAL,
)
from app.db.models import VideoJob, VideoJobStatus
from app.db.session import SessionLocal
from app.services.object_storage_service import ObjectStorageError, ObjectStorageService
from app.services.processing_service import ProcessingError, ProcessingService
from app.utils.error_messages import sanitize_error_message
from app.utils.object_keys import processed_object_key, s3_uri, thumbnail_object_key

configure_logging(log_level=settings.log_level, log_json=settings.log_json)
log = get_logger(__name__)


def _worker_identifier() -> str:
    return os.environ.get("RQ_WORKER_NAME") or f"{socket.gethostname()}:{os.getpid()}"


def _is_local_job(job: VideoJob) -> bool:
    return (job.storage_backend or "local") == "local"


def _storage_backend_label(job: VideoJob | None) -> str:
    if job is None:
        return "unknown"
    return job.storage_backend or "local"


def _record_processing_success(job: VideoJob, duration_s: float) -> None:
    backend = _storage_backend_label(job)
    VIDEO_PROCESSING_JOBS_TOTAL.labels(status="completed", storage_backend=backend).inc()
    VIDEO_PROCESSING_DURATION_SECONDS.labels(storage_backend=backend).observe(duration_s)


def _clear_failure_metadata(job: VideoJob) -> None:
    job.error_message = None
    job.failed_at = None
    job.last_error_type = None
    job.retry_exhausted = False


def _mark_job_failed(job: VideoJob, exc: BaseException, processing_start: datetime | None) -> None:
    now = datetime.now(timezone.utc)
    job.status = VideoJobStatus.FAILED
    job.error_message = sanitize_error_message(exc)
    job.last_error_type = type(exc).__name__
    job.failed_at = now
    job.retry_exhausted = job.attempt_count >= job.max_attempts
    if processing_start is not None:
        job.processing_completed_at = now
        job.processing_duration_seconds = (now - processing_start).total_seconds()


def _should_rq_retry(job: VideoJob) -> bool:
    """True when another worker attempt should run (DB attempt budget not exhausted)."""
    return job.attempt_count < job.max_attempts


def _record_processing_failure(
    job: VideoJob | None,
    *,
    error_type: str,
    duration_s: float | None,
) -> None:
    backend = _storage_backend_label(job)
    VIDEO_PROCESSING_JOBS_TOTAL.labels(status="failed", storage_backend=backend).inc()
    VIDEO_PROCESSING_FAILURES_TOTAL.labels(storage_backend=backend, error_type=error_type).inc()
    if duration_s is not None:
        VIDEO_PROCESSING_DURATION_SECONDS.labels(storage_backend=backend).observe(duration_s)


def process_video_job(job_id: str) -> None:
    """Load job from DB, transcode with FFmpeg, update status. Uses its own DB session (no FastAPI)."""
    worker_id = _worker_identifier()
    log.info("worker_job_picked_up", video_id=job_id, worker_id=worker_id)
    db = SessionLocal()
    processing_start: datetime | None = None
    try:
        job = db.get(VideoJob, job_id)
        if job is None:
            log.warning("worker_job_not_found", video_id=job_id, worker_id=worker_id)
            return
        if job.status == VideoJobStatus.COMPLETED:
            log.info(
                "worker_job_finished",
                outcome="skipped",
                reason="already_completed",
                video_id=job_id,
                worker_id=worker_id,
            )
            return
        if job.status == VideoJobStatus.FAILED and (
            job.retry_exhausted or job.attempt_count >= job.max_attempts
        ):
            log.info(
                "worker_job_finished",
                outcome="skipped",
                reason="max_attempts_exhausted",
                video_id=job_id,
                worker_id=worker_id,
                attempt_count=job.attempt_count,
                max_attempts=job.max_attempts,
            )
            return

        if job.status == VideoJobStatus.FAILED:
            job.error_message = None
        elif job.status == VideoJobStatus.PROCESSING:
            job.error_message = None

        processing_start = datetime.now(timezone.utc)
        job.processing_started_at = processing_start
        job.attempt_count += 1
        job.status = VideoJobStatus.PROCESSING
        db.commit()
        db.refresh(job)
        log.info(
            "worker_processing_started",
            video_id=job_id,
            worker_id=worker_id,
            attempt_count=job.attempt_count,
            storage_backend=job.storage_backend,
        )

        processing = ProcessingService()
        if _is_local_job(job):
            if not job.raw_path:
                raise ProcessingError("missing raw_path for local job")
            raw_path = Path(job.raw_path)
            processed, thumbnail = processing.process(job_id, raw_path)
            job.processed_path = str(processed)
            job.thumbnail_path = str(thumbnail)
        else:
            if not job.raw_object_key:
                raise ProcessingError("missing raw_object_key for object job")
            pk = processed_object_key(job.id)
            tk = thumbnail_object_key(job.id)
            suffix = Path(job.original_filename).suffix or ".bin"
            with tempfile.TemporaryDirectory() as td:
                tdir = Path(td)
                raw_local = tdir / f"input{suffix}"
                out_mp4 = tdir / f"{job.id}.mp4"
                out_thumb = tdir / f"{job.id}.jpg"
                obj = ObjectStorageService()
                obj.download_file(settings.raw_video_bucket, job.raw_object_key, str(raw_local))
                processing.process_paths(raw_local, out_mp4, out_thumb)
                obj.upload_file(settings.processed_video_bucket, pk, str(out_mp4))
                obj.upload_file(settings.thumbnail_bucket, tk, str(out_thumb))
                job.processed_object_key = pk
                job.thumbnail_object_key = tk
                job.processed_path = s3_uri(settings.processed_video_bucket, pk)
                job.thumbnail_path = s3_uri(settings.thumbnail_bucket, tk)

        completed_at = datetime.now(timezone.utc)
        duration_s = (completed_at - processing_start).total_seconds()
        output_bytes = 0
        try:
            if _is_local_job(job):
                output_bytes = Path(job.processed_path or "").stat().st_size + Path(
                    job.thumbnail_path or ""
                ).stat().st_size
            elif job.processed_object_key and job.thumbnail_object_key:
                obj = ObjectStorageService()
                output_bytes = obj.head_object_content_length(
                    settings.processed_video_bucket, job.processed_object_key
                ) + obj.head_object_content_length(settings.thumbnail_bucket, job.thumbnail_object_key)
        except (OSError, ObjectStorageError):
            pass

        _clear_failure_metadata(job)
        job.status = VideoJobStatus.COMPLETED
        job.processing_completed_at = completed_at
        job.processing_duration_seconds = duration_s
        db.commit()
        _record_processing_success(job, duration_s)
        log.info(
            "worker_job_finished",
            outcome="success",
            video_id=job_id,
            worker_id=worker_id,
            attempt_count=job.attempt_count,
            processing_duration_seconds=duration_s,
            output_bytes_total=output_bytes,
            storage_backend=job.storage_backend,
        )
    except ProcessingError as exc:
        db.rollback()
        job = db.get(VideoJob, job_id)
        if job is not None:
            _mark_job_failed(job, exc, processing_start)
            db.commit()
            duration_s = job.processing_duration_seconds
            _record_processing_failure(job, error_type=type(exc).__name__, duration_s=duration_s)
            outcome = "failure" if _should_rq_retry(job) else "permanent_failure"
            log.warning(
                "worker_job_finished",
                outcome=outcome,
                video_id=job_id,
                worker_id=worker_id,
                attempt_count=job.attempt_count,
                max_attempts=job.max_attempts,
                retry_exhausted=job.retry_exhausted,
                processing_duration_seconds=duration_s,
                error=str(exc),
            )
            if _should_rq_retry(job):
                raise
            return
        raise
    except Exception as exc:
        db.rollback()
        job = db.get(VideoJob, job_id)
        if job is not None:
            _mark_job_failed(job, exc, processing_start)
            db.commit()
            duration_s = job.processing_duration_seconds
            _record_processing_failure(
                job,
                error_type=type(exc).__name__,
                duration_s=duration_s,
            )
            outcome = "failure" if _should_rq_retry(job) else "permanent_failure"
            log_fn = log.exception if _should_rq_retry(job) else log.warning
            log_fn(
                "worker_job_finished",
                outcome=outcome,
                video_id=job_id,
                worker_id=worker_id,
                attempt_count=job.attempt_count,
                max_attempts=job.max_attempts,
                retry_exhausted=job.retry_exhausted,
                processing_duration_seconds=duration_s,
                error=str(exc),
            )
            if _should_rq_retry(job):
                raise
            return
        raise
    finally:
        db.close()
