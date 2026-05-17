from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import VideoJobStatus


class FailedJobItem(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: str
    original_filename: str
    status: VideoJobStatus
    storage_backend: str
    attempt_count: int
    max_attempts: int
    retry_exhausted: bool
    last_error_type: str | None = None
    error_message: str | None = None
    failed_at: datetime | None = None
    queue_job_id: str | None = None
    created_at: datetime
    updated_at: datetime


class FailedJobsResponse(BaseModel):
    jobs: list[FailedJobItem]
    count: int = Field(description="Number of jobs returned in this page.")


class StuckJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: str
    status: VideoJobStatus
    original_filename: str
    storage_backend: str
    queue_job_id: str | None = None
    attempt_count: int
    max_attempts: int
    retry_exhausted: bool
    processing_started_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    age_seconds: float
    stuck_reason: str


class StuckJobListResponse(BaseModel):
    jobs: list[StuckJobResponse]
    count: int


class RecoveryResultResponse(BaseModel):
    inspected_count: int
    recovered_count: int
    failed_count: int
    skipped_count: int
    recovered_job_ids: list[str]
    failed_job_ids: list[str]
    skipped_job_ids: list[str]
