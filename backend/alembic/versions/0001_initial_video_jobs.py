"""initial video_jobs schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

video_job_status = sa.Enum(
    "UPLOADED",
    "QUEUED",
    "PROCESSING",
    "COMPLETED",
    "FAILED",
    name="video_job_status",
    native_enum=False,
    length=32,
)


def upgrade() -> None:
    op.create_table(
        "video_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("status", video_job_status, nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("raw_path", sa.String(length=1024), nullable=True),
        sa.Column(
            "storage_backend",
            sa.String(length=16),
            server_default="local",
            nullable=False,
        ),
        sa.Column("raw_object_key", sa.String(length=1024), nullable=True),
        sa.Column("processed_object_key", sa.String(length=1024), nullable=True),
        sa.Column("thumbnail_object_key", sa.String(length=1024), nullable=True),
        sa.Column("queue_job_id", sa.String(length=128), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("processed_path", sa.String(length=1024), nullable=True),
        sa.Column("thumbnail_path", sa.String(length=1024), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_duration_seconds", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("video_jobs")
