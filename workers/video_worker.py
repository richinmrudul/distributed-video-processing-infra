"""RQ worker entrypoint: FFmpeg runs here, not in the API process."""

import os
import socket
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.models import VideoJob, VideoJobStatus
from app.db.session import SessionLocal
from app.services.processing_service import ProcessingError, ProcessingService

configure_logging(log_level=settings.log_level, log_json=settings.log_json)
log = get_logger(__name__)


def _worker_identifier() -> str:
    return os.environ.get("RQ_WORKER_NAME") or f"{socket.gethostname()}:{os.getpid()}"


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
        if job.status == VideoJobStatus.FAILED and job.attempt_count >= job.max_attempts:
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
        )

        processing = ProcessingService()
        raw_path = Path(job.raw_path)
        processed, thumbnail = processing.process(job_id, raw_path)

        completed_at = datetime.now(timezone.utc)
        duration_s = (completed_at - processing_start).total_seconds()
        output_bytes = 0
        try:
            output_bytes = processed.stat().st_size + thumbnail.stat().st_size
        except OSError:
            pass

        job.processed_path = str(processed)
        job.thumbnail_path = str(thumbnail)
        job.error_message = None
        job.status = VideoJobStatus.COMPLETED
        job.processing_completed_at = completed_at
        job.processing_duration_seconds = duration_s
        db.commit()
        log.info(
            "worker_job_finished",
            outcome="success",
            video_id=job_id,
            worker_id=worker_id,
            attempt_count=job.attempt_count,
            processing_duration_seconds=duration_s,
            output_bytes_total=output_bytes,
        )
    except ProcessingError as exc:
        db.rollback()
        job = db.get(VideoJob, job_id)
        if job is not None:
            job.status = VideoJobStatus.FAILED
            job.error_message = str(exc)
            if processing_start is not None:
                completed_at = datetime.now(timezone.utc)
                job.processing_completed_at = completed_at
                job.processing_duration_seconds = (completed_at - processing_start).total_seconds()
            db.commit()
            duration_s = job.processing_duration_seconds
            log.warning(
                "worker_job_finished",
                outcome="failure",
                video_id=job_id,
                worker_id=worker_id,
                attempt_count=job.attempt_count,
                processing_duration_seconds=duration_s,
                error=str(exc),
            )
        raise
    except Exception as exc:
        db.rollback()
        job = db.get(VideoJob, job_id)
        if job is not None:
            job.status = VideoJobStatus.FAILED
            job.error_message = str(exc)[:8000]
            if processing_start is not None:
                completed_at = datetime.now(timezone.utc)
                job.processing_completed_at = completed_at
                job.processing_duration_seconds = (completed_at - processing_start).total_seconds()
            db.commit()
            duration_s = job.processing_duration_seconds
            log.exception(
                "worker_job_finished",
                outcome="failure",
                video_id=job_id,
                worker_id=worker_id,
                attempt_count=job.attempt_count,
                processing_duration_seconds=duration_s,
            )
        raise
    finally:
        db.close()
