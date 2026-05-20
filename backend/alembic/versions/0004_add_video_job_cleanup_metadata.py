"""add video job cleanup metadata

Revision ID: 0004_cleanup_metadata
Revises: 0003_idempotency_key
Create Date: 2026-05-19

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_cleanup_metadata"
down_revision: Union[str, None] = "0003_idempotency_key"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("video_jobs", sa.Column("cleaned_up_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("video_jobs", sa.Column("cleanup_error_message", sa.Text(), nullable=True))
    op.create_index("ix_video_jobs_cleaned_up_at", "video_jobs", ["cleaned_up_at"])


def downgrade() -> None:
    op.drop_index("ix_video_jobs_cleaned_up_at", table_name="video_jobs")
    op.drop_column("video_jobs", "cleanup_error_message")
    op.drop_column("video_jobs", "cleaned_up_at")
