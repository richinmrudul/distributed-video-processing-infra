from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import VideoJob, VideoJobStatus
from app.services.queue_service import QueueService
from app.services.storage_service import StorageService
from app.utils.ids import new_video_id

log = get_logger(__name__)


class VideoService:
    """Coordinates persistence, storage, and queueing. FFmpeg runs in RQ workers (see workers.video_worker)."""

    def __init__(
        self,
        storage: StorageService | None = None,
        queue: QueueService | None = None,
    ) -> None:
        self._storage = storage or StorageService()
        self._queue = queue or QueueService()

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
            attempt_count=0,
            max_attempts=3,
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        log.info("video_uploaded", video_id=video_id, raw_path=str(raw_path))

        try:
            rq_job_id = self._queue.enqueue_video_processing(video_id, max_attempts=job.max_attempts)
        except Exception as exc:
            log.exception("video_enqueue_failed", video_id=video_id)
            job.status = VideoJobStatus.FAILED
            job.error_message = f"enqueue_failed: {exc}"
            db.commit()
            db.refresh(job)
            return job

        job.queue_job_id = rq_job_id
        job.status = VideoJobStatus.QUEUED
        db.commit()
        db.refresh(job)
        log.info("video_queued", video_id=video_id, rq_job_id=rq_job_id)
        return job

    def get_job(self, db: Session, video_id: str) -> VideoJob | None:
        return db.get(VideoJob, video_id)
