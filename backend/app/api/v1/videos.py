from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import VideoJob, VideoJobStatus
from app.db.session import get_db
from app.schemas.video import VideoAssetsResponse, VideoStatusResponse, VideoUploadResponse
from app.services.object_storage_service import ObjectStorageError, ObjectStorageService
from app.services.video_service import VideoService

router = APIRouter()
log = get_logger(__name__)


def get_video_service() -> VideoService:
    return VideoService()


def _get_video_job(db: Session, video_id: str) -> VideoJob | None:
    """Load VideoJob by primary key (same lookup for status and assets)."""
    vid = video_id.strip()
    return db.execute(select(VideoJob).where(VideoJob.id == vid)).scalar_one_or_none()


@router.post(
    "/upload",
    response_model=VideoUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_video(
    file: UploadFile = File(..., description="Video file to store; processing runs asynchronously via RQ."),
    db: Session = Depends(get_db),
    service: VideoService = Depends(get_video_service),
) -> VideoUploadResponse:
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="filename is required")
    job = await service.upload_and_process(db, file)
    if job.status == VideoJobStatus.FAILED and (job.error_message or "").startswith("enqueue_failed"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "queue_unavailable",
                "message": job.error_message,
                "video_id": job.id,
            },
        )
    return VideoUploadResponse.model_validate(job)


# Register before /{video_id}/status so literal path segments are not shadowed by another dynamic route.
@router.get("/{video_id}/assets", response_model=VideoAssetsResponse)
def get_video_assets(
    video_id: str,
    db: Session = Depends(get_db),
) -> VideoAssetsResponse:
    job = _get_video_job(db, video_id)
    log.info(
        "video_assets_lookup",
        requested_video_id=video_id,
        normalized_video_id=video_id.strip(),
        job_found=job is not None,
        job_status=str(job.status) if job is not None else None,
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video job not found")

    if (job.storage_backend or "local") != "object":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "unsupported_storage_backend",
                "message": "The assets endpoint currently supports object storage mode only (STORAGE_BACKEND=object).",
                "storage_backend": job.storage_backend,
            },
        )

    if job.status != VideoJobStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "assets_not_ready",
                "message": "Assets are not ready yet; wait until processing completes.",
                "status": job.status.value if hasattr(job.status, "value") else str(job.status),
            },
        )

    expires = settings.presigned_url_expires_seconds
    obj = ObjectStorageService()

    def _url(bucket: str, key: str | None) -> str | None:
        if not key:
            return None
        try:
            return obj.generate_presigned_url(bucket, key, expires_in_seconds=expires)
        except ObjectStorageError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": "presigned_url_failed", "message": str(exc)},
            ) from exc

    return VideoAssetsResponse(
        video_id=job.id,
        storage_backend=job.storage_backend,
        status=job.status,
        expires_in_seconds=expires,
        raw_url=_url(settings.raw_video_bucket, job.raw_object_key),
        processed_url=_url(settings.processed_video_bucket, job.processed_object_key),
        thumbnail_url=_url(settings.thumbnail_bucket, job.thumbnail_object_key),
    )


@router.get("/{video_id}/status", response_model=VideoStatusResponse)
def get_video_status(
    video_id: str,
    db: Session = Depends(get_db),
) -> VideoStatusResponse:
    job = _get_video_job(db, video_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video job not found")
    return VideoStatusResponse.model_validate(job)
