from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.schemas.jobs import FailedJobItem, FailedJobsResponse, RecoveryResultResponse, StuckJobListResponse
from app.schemas.video import VideoStatusResponse
from app.services.job_recovery_service import JobRecoveryService
from app.services.job_service import (
    JobEnqueueError,
    JobNotFoundError,
    JobRetryConflictError,
    JobService,
)

router = APIRouter()


def get_job_service() -> JobService:
    return JobService()


def get_job_recovery_service() -> JobRecoveryService:
    return JobRecoveryService()


@router.get("/failed", response_model=FailedJobsResponse)
def list_failed_jobs(
    limit: int = Query(20, ge=1, le=100),
    retry_exhausted: bool | None = Query(None, description="Filter by retry exhaustion."),
    db: Session = Depends(get_db),
    service: JobService = Depends(get_job_service),
) -> FailedJobsResponse:
    jobs = service.list_failed_jobs(db, limit=limit, retry_exhausted=retry_exhausted)
    items = [FailedJobItem.model_validate(j) for j in jobs]
    return FailedJobsResponse(jobs=items, count=len(items))


# Operational endpoint; add auth before exposing outside trusted admin/dev networks.
@router.get("/stuck", response_model=StuckJobListResponse)
def list_stuck_jobs(
    db: Session = Depends(get_db),
    service: JobRecoveryService = Depends(get_job_recovery_service),
) -> StuckJobListResponse:
    jobs = service.find_stuck_jobs(db)
    return StuckJobListResponse(jobs=jobs, count=len(jobs))


# Operational endpoint; add auth before exposing outside trusted admin/dev networks.
@router.post("/recover-stuck", response_model=RecoveryResultResponse)
def recover_stuck_jobs(
    db: Session = Depends(get_db),
    service: JobRecoveryService = Depends(get_job_recovery_service),
) -> RecoveryResultResponse:
    if not settings.stuck_job_recovery_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "stuck_job_recovery_disabled",
                "message": "Stuck job recovery is disabled; use GET /api/v1/jobs/stuck for report-only mode.",
            },
        )
    return service.recover_stuck_jobs(db)


@router.post("/{video_id}/retry", response_model=VideoStatusResponse)
def retry_failed_job(
    video_id: str,
    db: Session = Depends(get_db),
    service: JobService = Depends(get_job_service),
) -> VideoStatusResponse:
    try:
        job = service.retry_failed_job(db, video_id)
    except JobNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video job not found") from None
    except JobRetryConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "retry_not_allowed", "message": str(exc)},
        ) from exc
    except JobEnqueueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "queue_unavailable", "message": str(exc)},
        ) from exc
    return VideoStatusResponse.model_validate(job)
