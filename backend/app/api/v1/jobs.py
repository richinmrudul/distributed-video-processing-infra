from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.admin_auth import require_admin_api_key
from app.core.config import settings
from app.db.session import get_db
from app.schemas.jobs import (
    CleanupCandidateItem,
    CleanupCandidatesResponse,
    CleanupFailureItem,
    CleanupResultResponse,
    FailedJobItem,
    FailedJobsResponse,
    RecoveryResultResponse,
    StuckJobListResponse,
)
from app.schemas.video import VideoStatusResponse
from app.services.job_cleanup_service import JobCleanupService
from app.services.job_recovery_service import JobRecoveryService
from app.services.job_service import (
    JobEnqueueError,
    JobNotFoundError,
    JobRetryConflictError,
    JobService,
)

router = APIRouter(dependencies=[Depends(require_admin_api_key)])


def get_job_service() -> JobService:
    return JobService()


def get_job_recovery_service() -> JobRecoveryService:
    return JobRecoveryService()


def get_job_cleanup_service() -> JobCleanupService:
    return JobCleanupService()


@router.get(
    "/failed",
    response_model=FailedJobsResponse,
    summary="List failed video jobs",
    description="Admin endpoint. Requires the X-Admin-API-Key header.",
)
def list_failed_jobs(
    limit: int = Query(20, ge=1, le=100),
    retry_exhausted: bool | None = Query(None, description="Filter by retry exhaustion."),
    db: Session = Depends(get_db),
    service: JobService = Depends(get_job_service),
) -> FailedJobsResponse:
    jobs = service.list_failed_jobs(db, limit=limit, retry_exhausted=retry_exhausted)
    items = [FailedJobItem.model_validate(j) for j in jobs]
    return FailedJobsResponse(jobs=items, count=len(items))


@router.get(
    "/stuck",
    response_model=StuckJobListResponse,
    summary="List stuck video jobs",
    description="Admin endpoint. Requires the X-Admin-API-Key header.",
)
def list_stuck_jobs(
    db: Session = Depends(get_db),
    service: JobRecoveryService = Depends(get_job_recovery_service),
) -> StuckJobListResponse:
    jobs = service.find_stuck_jobs(db)
    return StuckJobListResponse(jobs=jobs, count=len(jobs))


@router.post(
    "/recover-stuck",
    response_model=RecoveryResultResponse,
    summary="Recover stuck video jobs",
    description="Admin endpoint. Requires the X-Admin-API-Key header.",
)
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


@router.get(
    "/cleanup-candidates",
    response_model=CleanupCandidatesResponse,
    summary="List cleanup candidate video jobs",
    description="Admin endpoint. Requires the X-Admin-API-Key header. Dry-run style candidate inspection only.",
)
def list_cleanup_candidates(
    status_filter: str | None = Query(None, alias="status", description="Optional COMPLETED or FAILED filter."),
    limit: int = Query(settings.cleanup_batch_size, ge=1, le=500),
    completed_after_days: int | None = Query(None, ge=0),
    failed_after_days: int | None = Query(None, ge=0),
    db: Session = Depends(get_db),
    service: JobCleanupService = Depends(get_job_cleanup_service),
) -> CleanupCandidatesResponse:
    candidates = service.find_cleanup_candidates(
        db,
        status_filter=status_filter,
        limit=limit,
        completed_after_days=completed_after_days,
        failed_after_days=failed_after_days,
    )
    items = [CleanupCandidateItem.model_validate(candidate) for candidate in candidates]
    return CleanupCandidatesResponse(candidates=items, count=len(items))


@router.post(
    "/cleanup",
    response_model=CleanupResultResponse,
    summary="Clean up retained video job assets",
    description="Admin endpoint. Requires the X-Admin-API-Key header. Defaults to dry-run mode.",
)
def cleanup_jobs(
    dry_run: bool = Query(True),
    limit: int = Query(settings.cleanup_batch_size, ge=1, le=500),
    completed_after_days: int | None = Query(None, ge=0),
    failed_after_days: int | None = Query(None, ge=0),
    delete_db_rows: bool = Query(False),
    db: Session = Depends(get_db),
    service: JobCleanupService = Depends(get_job_cleanup_service),
) -> CleanupResultResponse:
    result = service.cleanup(
        db,
        dry_run=dry_run,
        limit=limit,
        completed_after_days=completed_after_days,
        failed_after_days=failed_after_days,
        delete_db_rows=delete_db_rows,
    )
    return CleanupResultResponse(
        dry_run=result.dry_run,
        inspected_count=result.inspected_count,
        candidate_count=result.candidate_count,
        cleaned_count=result.cleaned_count,
        failed_count=result.failed_count,
        skipped_count=result.skipped_count,
        candidates=[CleanupCandidateItem.model_validate(candidate) for candidate in result.candidates],
        cleaned_job_ids=result.cleaned_job_ids,
        failures=[CleanupFailureItem.model_validate(failure) for failure in result.failures],
    )


@router.post(
    "/{video_id}/retry",
    response_model=VideoStatusResponse,
    summary="Retry failed video job",
    description="Admin endpoint. Requires the X-Admin-API-Key header.",
)
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
