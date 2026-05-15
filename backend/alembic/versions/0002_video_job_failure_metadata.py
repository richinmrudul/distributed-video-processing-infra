"""video job failure metadata

Revision ID: 0002_failure_metadata
Revises: 0001_initial
Create Date: 2026-05-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_failure_metadata"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("video_jobs", sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("video_jobs", sa.Column("last_error_type", sa.String(length=128), nullable=True))
    op.add_column(
        "video_jobs",
        sa.Column("retry_exhausted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "video_jobs",
        sa.Column("manually_retried_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "video_jobs",
        sa.Column("manual_retry_count", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("video_jobs", "manual_retry_count")
    op.drop_column("video_jobs", "manually_retried_at")
    op.drop_column("video_jobs", "retry_exhausted")
    op.drop_column("video_jobs", "last_error_type")
    op.drop_column("video_jobs", "failed_at")
