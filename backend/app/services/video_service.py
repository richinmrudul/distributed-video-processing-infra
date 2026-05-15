import os
import tempfile
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import VideoJob, VideoJobStatus
from app.services.object_storage_service import ObjectStorageService
from app.services.queue_service import QueueService
from app.services.storage_service import StorageService
from app.utils.ids import new_video_id
from app.utils.object_keys import raw_object_key, s3_uri

log = get_logger(__name__)

CHUNK = 1024 * 1024


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

        if settings.storage_backend == "object":
            return await self._upload_object_mode(db, upload, video_id, filename)
        return await self._upload_local_mode(db, upload, video_id, filename)

    async def _upload_local_mode(self, db: Session, upload: UploadFile, video_id: str, filename: str) -> VideoJob:
        raw_path = await self._storage.save_raw_upload(video_id, upload)

        job = VideoJob(
            id=video_id,
            status=VideoJobStatus.UPLOADED,
            original_filename=filename,
            content_type=upload.content_type,
            storage_backend="local",
            raw_path=str(raw_path),
            attempt_count=0,
            max_attempts=3,
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        log.info("video_uploaded", video_id=video_id, raw_path=str(raw_path), storage_backend="local")

        return self._enqueue_or_fail(db, job, video_id)

    async def _upload_object_mode(self, db: Session, upload: UploadFile, video_id: str, filename: str) -> VideoJob:
        rkey = raw_object_key(video_id, filename)
        bucket = settings.raw_video_bucket
        dbg_uri = s3_uri(bucket, rkey)

        job = VideoJob(
            id=video_id,
            status=VideoJobStatus.UPLOADED,
            original_filename=filename,
            content_type=upload.content_type,
            storage_backend="object",
            raw_object_key=rkey,
            raw_path=dbg_uri,
            attempt_count=0,
            max_attempts=3,
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        tmp_path: str | None = None
        try:
            suffix = Path(filename).suffix or ".bin"
            fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix="upload-")
            os.close(fd)
            with Path(tmp_path).open("wb") as out:
                while True:
                    chunk = await upload.read(CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
            await upload.close()

            obj = ObjectStorageService()
            obj.upload_file(bucket, rkey, tmp_path)
        except Exception as exc:
            log.exception("video_object_upload_failed", video_id=video_id)
            job.status = VideoJobStatus.FAILED
            job.error_message = f"object_upload_failed: {exc}"
            db.commit()
            db.refresh(job)
            return job
        finally:
            if tmp_path and os.path.isfile(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        log.info("video_uploaded_object", video_id=video_id, raw_object_key=rkey, bucket=bucket)

        return self._enqueue_or_fail(db, job, video_id)

    def _enqueue_or_fail(self, db: Session, job: VideoJob, video_id: str) -> VideoJob:
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
        vid = video_id.strip()
        return db.execute(select(VideoJob).where(VideoJob.id == vid)).scalar_one_or_none()
