from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import VideoJob, VideoJobStatus
from app.services.processing_service import ProcessingError, ProcessingService
from app.services.storage_service import StorageService
from app.utils.ids import new_video_id

log = get_logger(__name__)


class VideoService:
    """Coordinates persistence, storage, and processing. Replace synchronous process() with enqueue in Phase 2."""

    def __init__(
        self,
        storage: StorageService | None = None,
        processing: ProcessingService | None = None,
    ) -> None:
        self._storage = storage or StorageService()
        self._processing = processing or ProcessingService()

    async def upload_and_process(self, db: Session, upload: UploadFile) -> VideoJob:
        filename = upload.filename or "video"
        video_id = new_video_id()

        raw_path = await self._storage.save_raw_upload(video_id, upload)

        job = VideoJob(
            id=video_id,
            status=VideoJobStatus.UPLOADED,
            original_filename=filename,
            content_type=upload.content_type,
            raw_path=str(raw_path),
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        log.info("video_uploaded", video_id=video_id, raw_path=str(raw_path))

        self._run_processing(db, job, raw_path)
        return job

    def _run_processing(self, db: Session, job: VideoJob, raw_path: Path) -> None:
        job.status = VideoJobStatus.PROCESSING
        db.commit()
        db.refresh(job)
        log.info("video_processing_started", video_id=job.id)

        try:
            processed, thumbnail = self._processing.process(job.id, raw_path)
            job.status = VideoJobStatus.COMPLETED
            job.processed_path = str(processed)
            job.thumbnail_path = str(thumbnail)
            job.error_message = None
            log.info(
                "video_processing_completed",
                video_id=job.id,
                processed_path=str(processed),
                thumbnail_path=str(thumbnail),
            )
        except ProcessingError as exc:
            job.status = VideoJobStatus.FAILED
            job.error_message = str(exc)
            log.warning("video_processing_failed", video_id=job.id, error=str(exc))
        db.commit()
        db.refresh(job)

    def get_job(self, db: Session, video_id: str) -> VideoJob | None:
        return db.get(VideoJob, video_id)
