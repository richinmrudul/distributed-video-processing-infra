import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import VIDEO_UPLOADS_TOTAL
from app.core.tracing import start_span
from app.db.models import VideoJob, VideoJobStatus
from app.services.object_storage_service import ObjectStorageService
from app.services.queue_service import QueueService
from app.services.storage_service import StorageService
from app.utils.ids import new_video_id
from app.utils.object_keys import raw_object_key, s3_uri

log = get_logger(__name__)

CHUNK = 1024 * 1024


@dataclass(frozen=True)
class VideoUploadResult:
    job: VideoJob
    idempotency_outcome: str = "new_key"


def _record_upload_metric(job: VideoJob) -> None:
    backend = job.storage_backend or settings.storage_backend or "local"
    if job.status == VideoJobStatus.QUEUED:
        upload_status = "queued"
    elif job.status == VideoJobStatus.FAILED:
        upload_status = "failed"
    else:
        upload_status = str(job.status.value).lower()
    VIDEO_UPLOADS_TOTAL.labels(storage_backend=backend, status=upload_status).inc()


class VideoService:
    """Coordinates persistence, storage, and queueing. FFmpeg runs in RQ workers (see workers.video_worker)."""

    def __init__(
        self,
        storage: StorageService | None = None,
        queue: QueueService | None = None,
    ) -> None:
        self._storage = storage or StorageService()
        self._queue = queue or QueueService()

    async def upload_and_process(
        self,
        db: Session,
        upload: UploadFile,
        *,
        idempotency_key: str | None = None,
    ) -> VideoUploadResult:
        filename = upload.filename or "video"
        video_id = new_video_id()

        if settings.storage_backend == "object":
            result = await self._upload_object_mode(db, upload, video_id, filename, idempotency_key)
        else:
            result = await self._upload_local_mode(db, upload, video_id, filename, idempotency_key)
        if result.idempotency_outcome == "new_key":
            _record_upload_metric(result.job)
        return result

    async def _upload_local_mode(
        self,
        db: Session,
        upload: UploadFile,
        video_id: str,
        filename: str,
        idempotency_key: str | None,
    ) -> VideoUploadResult:
        with start_span(
            "app.video",
            "create_video_job",
            attributes={
                "video.id": video_id,
                "storage.backend": "local",
                "idempotency.present": idempotency_key is not None,
            },
        ):
            job = VideoJob(
                id=video_id,
                idempotency_key=idempotency_key,
                status=VideoJobStatus.UPLOADED,
                original_filename=filename,
                content_type=upload.content_type,
                storage_backend="local",
                raw_path=None,
                attempt_count=0,
                max_attempts=3,
            )
            job, raced = self._commit_new_job_or_get_existing(db, job, idempotency_key)
            if raced:
                return VideoUploadResult(job=job, idempotency_outcome="race_existing")

        with start_span(
            "app.video",
            "save_raw_upload_local",
            attributes={"video.id": video_id, "storage.backend": "local"},
        ):
            raw_path = await self._storage.save_raw_upload(video_id, upload)
            job.raw_path = str(raw_path)
            db.commit()
            db.refresh(job)

        log.info("video_uploaded", video_id=video_id, raw_path=str(raw_path), storage_backend="local")
        return VideoUploadResult(job=self._enqueue_or_fail(db, job, video_id), idempotency_outcome="new_key")

    async def _upload_object_mode(
        self,
        db: Session,
        upload: UploadFile,
        video_id: str,
        filename: str,
        idempotency_key: str | None,
    ) -> VideoUploadResult:
        rkey = raw_object_key(video_id, filename)
        bucket = settings.raw_video_bucket
        dbg_uri = s3_uri(bucket, rkey)

        with start_span(
            "app.video",
            "create_video_job",
            attributes={
                "video.id": video_id,
                "storage.backend": "object",
                "object.bucket": bucket,
                "object.key": rkey,
                "idempotency.present": idempotency_key is not None,
            },
        ):
            job = VideoJob(
                id=video_id,
                idempotency_key=idempotency_key,
                status=VideoJobStatus.UPLOADED,
                original_filename=filename,
                content_type=upload.content_type,
                storage_backend="object",
                raw_object_key=rkey,
                raw_path=dbg_uri,
                attempt_count=0,
                max_attempts=3,
            )
            job, raced = self._commit_new_job_or_get_existing(db, job, idempotency_key)
            if raced:
                return VideoUploadResult(job=job, idempotency_outcome="race_existing")

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

            with start_span(
                "app.video",
                "upload_raw_to_object_storage",
                attributes={
                    "video.id": video_id,
                    "storage.backend": "object",
                    "object.bucket": bucket,
                    "object.key": rkey,
                },
            ):
                obj = ObjectStorageService()
                obj.upload_file(bucket, rkey, tmp_path)
        except Exception as exc:
            log.exception("video_object_upload_failed", video_id=video_id)
            job.status = VideoJobStatus.FAILED
            job.error_message = f"object_upload_failed: {exc}"
            db.commit()
            db.refresh(job)
            return VideoUploadResult(job=job, idempotency_outcome="new_key")
        finally:
            if tmp_path and os.path.isfile(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        log.info("video_uploaded_object", video_id=video_id, raw_object_key=rkey, bucket=bucket)
        return VideoUploadResult(job=self._enqueue_or_fail(db, job, video_id), idempotency_outcome="new_key")

    def _commit_new_job_or_get_existing(
        self,
        db: Session,
        job: VideoJob,
        idempotency_key: str | None,
    ) -> tuple[VideoJob, bool]:
        db.add(job)
        try:
            db.commit()
            db.refresh(job)
            return job, False
        except IntegrityError:
            db.rollback()
            if idempotency_key is None:
                raise
            existing = self.get_job_by_idempotency_key(db, idempotency_key)
            if existing is None:
                raise
            return existing, True

    def _enqueue_or_fail(self, db: Session, job: VideoJob, video_id: str) -> VideoJob:
        try:
            with start_span(
                "app.video",
                "enqueue_video_processing",
                attributes={
                    "video.id": video_id,
                    "storage.backend": job.storage_backend or settings.storage_backend,
                    "queue.name": settings.queue_name,
                },
            ):
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

    def get_job_by_idempotency_key(self, db: Session, idempotency_key: str) -> VideoJob | None:
        return db.execute(select(VideoJob).where(VideoJob.idempotency_key == idempotency_key)).scalar_one_or_none()
