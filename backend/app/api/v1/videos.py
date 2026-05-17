from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import VideoJob, VideoJobStatus
from app.db.session import get_db
from app.schemas.video import VideoAssetsResponse, VideoStatusResponse, VideoUploadResponse
from app.services.admission_control import UploadAdmissionController
from app.services.object_storage_service import ObjectStorageError, ObjectStorageService
from app.services.rate_limiter import UploadRateLimiter
from app.services.upload_validation import UploadValidationDecision, UploadValidator
from app.services.video_service import VideoService

router = APIRouter()
log = get_logger(__name__)


def get_video_service() -> VideoService:
    return VideoService()


def get_upload_admission_controller() -> UploadAdmissionController:
    return UploadAdmissionController()


def get_upload_rate_limiter() -> UploadRateLimiter:
    return UploadRateLimiter()


def get_upload_validator() -> UploadValidator:
    return UploadValidator()


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
    request: Request,
    db: Session = Depends(get_db),
    service: VideoService = Depends(get_video_service),
    rate_limiter: UploadRateLimiter = Depends(get_upload_rate_limiter),
    admission: UploadAdmissionController = Depends(get_upload_admission_controller),
    validator: UploadValidator = Depends(get_upload_validator),
) -> VideoUploadResponse:
    rate_limit = rate_limiter.check_upload_allowed(request)
    if not rate_limit.allowed:
        if rate_limit.reason == "rate_limiter_unavailable":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "detail": "Upload rejected by rate limiter",
                    "reason": rate_limit.reason,
                    "limit": rate_limit.limit,
                    "remaining": rate_limit.remaining,
                    "reset_seconds": rate_limit.reset_seconds,
                },
            )
        headers = {
            "X-RateLimit-Limit": str(rate_limit.limit),
            "X-RateLimit-Remaining": str(rate_limit.remaining),
            "X-RateLimit-Reset": str(rate_limit.reset_seconds),
            "Retry-After": str(rate_limit.reset_seconds),
        }
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "detail": "Upload rejected by rate limiter",
                "reason": "rate_limited",
                "limit": rate_limit.limit,
                "remaining": rate_limit.remaining,
                "reset_seconds": rate_limit.reset_seconds,
            },
            headers=headers,
        )

    decision = admission.check_upload_allowed()
    if not decision.allowed:
        http_status = (
            status.HTTP_429_TOO_MANY_REQUESTS
            if decision.reason == "queue_backlog_high"
            else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        raise HTTPException(
            status_code=http_status,
            detail={
                "detail": "Upload rejected by admission control",
                "reason": decision.reason,
                "queue_depth": decision.queue_depth,
                "worker_count": decision.worker_count,
                "max_queue_depth": settings.max_queue_depth_for_uploads,
                "min_available_workers": settings.min_available_workers_for_uploads,
            },
        )

    metadata_validation = validator.validate_request_metadata(request)
    if not metadata_validation.allowed:
        raise _upload_validation_exception(metadata_validation)

    form = await request.form()
    file = form.get("file")
    if not isinstance(file, UploadFile) and not all(hasattr(file, attr) for attr in ("filename", "read", "close")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="file is required")
    file_validation = validator.validate_upload_file(file)
    if not file_validation.allowed:
        await file.close()
        raise _upload_validation_exception(file_validation)

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


def _upload_validation_exception(decision: UploadValidationDecision) -> HTTPException:
    reason = decision.reason or "upload_validation_failed"
    if reason == "upload_too_large":
        http_status = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    elif reason in ("unsupported_extension", "unsupported_content_type"):
        http_status = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    else:
        http_status = status.HTTP_400_BAD_REQUEST

    detail = {
        "detail": "Upload rejected by validation",
        "reason": reason,
        "max_bytes": decision.max_bytes,
        "content_length": decision.content_length,
    }
    if decision.filename is not None:
        detail["filename"] = decision.filename
    if decision.content_type is not None:
        detail["content_type"] = decision.content_type
    if reason == "unsupported_extension":
        detail["allowed_extensions"] = settings.allowed_video_extensions_list
    if reason == "unsupported_content_type":
        detail["allowed_content_types"] = settings.allowed_video_content_types_list
    return HTTPException(status_code=http_status, detail=detail)


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
