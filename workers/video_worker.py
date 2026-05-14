"""RQ worker entrypoint: FFmpeg runs here, not in the API process."""

from pathlib import Path

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.models import VideoJob, VideoJobStatus
from app.db.session import SessionLocal
from app.services.processing_service import ProcessingError, ProcessingService

configure_logging(log_level=settings.log_level, log_json=settings.log_json)
log = get_logger(__name__)


def process_video_job(job_id: str) -> None:
    """Load job from DB, transcode with FFmpeg, update status. Uses its own DB session (no FastAPI)."""
    log.info("worker_job_picked_up", video_id=job_id)
    db = SessionLocal()
    try:
        job = db.get(VideoJob, job_id)
        if job is None:
            log.warning("worker_job_not_found", video_id=job_id)
            return
        if job.status == VideoJobStatus.COMPLETED:
            log.info("worker_job_already_completed_skip", video_id=job_id)
            return
        if job.status == VideoJobStatus.FAILED and job.attempt_count >= job.max_attempts:
            log.info(
                "worker_max_attempts_exhausted_skip",
                video_id=job_id,
                attempt_count=job.attempt_count,
                max_attempts=job.max_attempts,
            )
            return

        if job.status == VideoJobStatus.FAILED:
            job.error_message = None
        elif job.status == VideoJobStatus.PROCESSING:
            job.error_message = None

        job.attempt_count += 1
        job.status = VideoJobStatus.PROCESSING
        db.commit()
        db.refresh(job)
        log.info("worker_processing_started", video_id=job_id, attempt_count=job.attempt_count)

        processing = ProcessingService()
        raw_path = Path(job.raw_path)
        processed, thumbnail = processing.process(job_id, raw_path)

        job.processed_path = str(processed)
        job.thumbnail_path = str(thumbnail)
        job.error_message = None
        job.status = VideoJobStatus.COMPLETED
        db.commit()
        log.info(
            "worker_processing_completed",
            video_id=job_id,
            processed_path=str(processed),
            thumbnail_path=str(thumbnail),
        )
    except ProcessingError as exc:
        db.rollback()
        job = db.get(VideoJob, job_id)
        if job is not None:
            job.status = VideoJobStatus.FAILED
            job.error_message = str(exc)
            db.commit()
        log.warning("worker_processing_failed", video_id=job_id, error=str(exc))
        raise
    except Exception as exc:
        db.rollback()
        job = db.get(VideoJob, job_id)
        if job is not None:
            job.status = VideoJobStatus.FAILED
            job.error_message = str(exc)[:8000]
            db.commit()
        log.exception("worker_processing_unexpected_error", video_id=job_id)
        raise
    finally:
        db.close()
