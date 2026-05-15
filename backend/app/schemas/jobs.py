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
