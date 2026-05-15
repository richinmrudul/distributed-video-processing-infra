import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class VideoJobStatus(str, enum.Enum):
    UPLOADED = "UPLOADED"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class VideoJob(Base):
    __tablename__ = "video_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[VideoJobStatus] = mapped_column(
        Enum(VideoJobStatus, name="video_job_status", native_enum=False, length=32),
        nullable=False,
    )
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    storage_backend: Mapped[str] = mapped_column(String(16), nullable=False, default="local", server_default="local")
    raw_object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    processed_object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    thumbnail_object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    queue_job_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    processed_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    retry_exhausted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    manually_retried_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    manual_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
