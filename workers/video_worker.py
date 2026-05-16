"""RQ worker entrypoint: FFmpeg runs here, not in the API process.

Worker metrics use the default prometheus_client registry in each worker process.
workers.run_worker starts prometheus_client HTTP /metrics on WORKER_METRICS_PORT (default 9100).
Prometheus discovers scaled worker containers via Docker DNS (job workers).
"""

import os
import socket
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opentelemetry import context as context_api, propagate, trace

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.metrics import (
    VIDEO_JOBS_FAILED_TOTAL,
    VIDEO_PROCESSING_DURATION_SECONDS,
    VIDEO_PROCESSING_FAILURES_TOTAL,
    VIDEO_PROCESSING_JOBS_TOTAL,
    VIDEO_RETRY_EXHAUSTED_TOTAL,
)
from app.core.tracing import configure_tracing, record_span_exception, start_span
from app.db.models import VideoJob, VideoJobStatus
from app.db.session import SessionLocal
from app.services.object_storage_service import ObjectStorageError, ObjectStorageService
from app.services.processing_service import ProcessingError, ProcessingService
from app.utils.error_messages import sanitize_error_message
from app.utils.object_keys import processed_object_key, s3_uri, thumbnail_object_key

configure_logging(log_level=settings.log_level, log_json=settings.log_json)
log = get_logger(__name__)

_tracing_ready = False


def _ensure_worker_tracing() -> None:
    global _tracing_ready
    if not _tracing_ready:
        configure_tracing(settings.otel_service_name)
        _tracing_ready = True


def _worker_identifier() -> str:
    return os.environ.get("RQ_WORKER_NAME") or f"{socket.gethostname()}:{os.getpid()}"


def _is_local_job(job: VideoJob) -> bool:
    return (job.storage_backend or "local") == "local"


def _storage_backend_label(job: VideoJob | None) -> str:
    if job is None:
        return "unknown"
    return job.storage_backend or "local"


def _job_span_attributes(job: VideoJob) -> dict[str, Any]:
    return {
        "video.id": job.id,
        "storage.backend": job.storage_backend or "local",
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "retry_exhausted": job.retry_exhausted,
    }


def _set_error_type_on_span(error_type: str) -> None:
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attribute("error.type", error_type)


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


def _record_job_lifecycle_failure(job: VideoJob, error_type: str) -> None:
    backend = _storage_backend_label(job)
    exhausted_label = "true" if job.retry_exhausted else "false"
    VIDEO_JOBS_FAILED_TOTAL.labels(
        storage_backend=backend,
        error_type=error_type,
        retry_exhausted=exhausted_label,
    ).inc()
    if job.retry_exhausted:
        VIDEO_RETRY_EXHAUSTED_TOTAL.labels(storage_backend=backend, error_type=error_type).inc()


def _run_processing(job: VideoJob, job_id: str, processing: ProcessingService) -> None:
    if _is_local_job(job):
        if not job.raw_path:
            raise ProcessingError("missing raw_path for local job")
        raw_path = Path(job.raw_path)
        with start_span(
            "workers.video_worker",
            "ffmpeg_process",
            attributes=_job_span_attributes(job),
        ):
            processed, thumbnail = processing.process(job_id, raw_path)
            job.processed_path = str(processed)
            job.thumbnail_path = str(thumbnail)
        return

    if not job.raw_object_key:
        raise ProcessingError("missing raw_object_key for object job")
    pk = processed_object_key(job.id)
    tk = thumbnail_object_key(job.id)
    suffix = Path(job.original_filename).suffix or ".bin"
    bucket_raw = settings.raw_video_bucket
    bucket_proc = settings.processed_video_bucket
    bucket_thumb = settings.thumbnail_bucket
    obj = ObjectStorageService()

    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        raw_local = tdir / f"input{suffix}"
        out_mp4 = tdir / f"{job.id}.mp4"
        out_thumb = tdir / f"{job.id}.jpg"

        with start_span(
            "workers.video_worker",
            "download_raw_object",
            attributes={
                **_job_span_attributes(job),
                "object.bucket": bucket_raw,
                "object.key": job.raw_object_key,
            },
        ):
            obj.download_file(bucket_raw, job.raw_object_key, str(raw_local))

        with start_span(
            "workers.video_worker",
            "ffmpeg_process",
            attributes=_job_span_attributes(job),
        ):
            processing.process_paths(raw_local, out_mp4, out_thumb)

        with start_span(
            "workers.video_worker",
            "upload_processed_object",
            attributes={
                **_job_span_attributes(job),
                "object.bucket": bucket_proc,
                "object.key": pk,
            },
        ):
            obj.upload_file(bucket_proc, pk, str(out_mp4))

        with start_span(
            "workers.video_worker",
            "upload_thumbnail_object",
            attributes={
                **_job_span_attributes(job),
                "object.bucket": bucket_thumb,
                "object.key": tk,
            },
        ):
            obj.upload_file(bucket_thumb, tk, str(out_thumb))

        job.processed_object_key = pk
        job.thumbnail_object_key = tk
        job.processed_path = s3_uri(bucket_proc, pk)
        job.thumbnail_path = s3_uri(bucket_thumb, tk)


def _process_video_job_impl(job_id: str) -> None:
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
        _run_processing(job, job_id, processing)

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

        with start_span(
            "workers.video_worker",
            "update_video_job_status",
            attributes={**_job_span_attributes(job), "job.status": "COMPLETED"},
        ):
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
            with start_span(
                "workers.video_worker",
                "update_video_job_status",
                attributes={**_job_span_attributes(job), "job.status": "FAILED"},
            ):
                db.commit()
            duration_s = job.processing_duration_seconds
            error_type = type(exc).__name__
            _set_error_type_on_span(error_type)
            _record_processing_failure(job, error_type=error_type, duration_s=duration_s)
            _record_job_lifecycle_failure(job, error_type)
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
            with start_span(
                "workers.video_worker",
                "update_video_job_status",
                attributes={**_job_span_attributes(job), "job.status": "FAILED"},
            ):
                db.commit()
            duration_s = job.processing_duration_seconds
            error_type = type(exc).__name__
            _set_error_type_on_span(error_type)
            _record_processing_failure(job, error_type=error_type, duration_s=duration_s)
            _record_job_lifecycle_failure(job, error_type)
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


def process_video_job(job_id: str, trace_context: dict | None = None) -> None:
    """Load job from DB, transcode with FFmpeg, update status. Uses its own DB session (no FastAPI)."""
    _ensure_worker_tracing()
    ctx = propagate.extract(trace_context or {})
    token = context_api.attach(ctx)
    try:
        with start_span(
            "workers.video_worker",
            "worker_process_video_job",
            attributes={"video.id": job_id},
        ):
            _process_video_job_impl(job_id)
    except Exception as exc:
        span = trace.get_current_span()
        if span.is_recording():
            record_span_exception(span, exc)
        raise
    finally:
        context_api.detach(token)
