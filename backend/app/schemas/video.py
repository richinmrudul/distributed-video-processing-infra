from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import VideoJobStatus


class VideoUploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: str = Field(..., description="Stable identifier for this upload and job.")
    idempotency_key: str | None = None
    status: VideoJobStatus
    original_filename: str
    raw_path: str | None = None
    storage_backend: str = "local"
    raw_object_key: str | None = None
    processed_object_key: str | None = None
    thumbnail_object_key: str | None = None
    queue_job_id: str | None = None
    attempt_count: int = 0
    max_attempts: int = 3


class VideoStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: str
    idempotency_key: str | None = None
    status: VideoJobStatus
    original_filename: str
    raw_path: str | None = None
    storage_backend: str = "local"
    raw_object_key: str | None = None
    processed_object_key: str | None = None
    thumbnail_object_key: str | None = None
    queue_job_id: str | None = None
    attempt_count: int = 0
    max_attempts: int = 3
    processed_path: str | None = None
    thumbnail_path: str | None = None
    error_message: str | None = None
    failed_at: datetime | None = None
    last_error_type: str | None = None
    retry_exhausted: bool = False
    manually_retried_at: datetime | None = None
    manual_retry_count: int = 0
    processing_started_at: datetime | None = None
    processing_completed_at: datetime | None = None
    processing_duration_seconds: float | None = None
    created_at: datetime
    updated_at: datetime


class VideoAssetsResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    video_id: str
    storage_backend: str
    status: VideoJobStatus
    expires_in_seconds: int
    raw_url: str | None = None
    processed_url: str | None = None
    thumbnail_url: str | None = None
