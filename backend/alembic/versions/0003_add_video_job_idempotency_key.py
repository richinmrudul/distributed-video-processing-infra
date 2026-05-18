"""add video job idempotency key

Revision ID: 0003_idempotency_key
Revises: 0002_failure_metadata
Create Date: 2026-05-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_idempotency_key"
down_revision: Union[str, None] = "0002_failure_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("video_jobs", sa.Column("idempotency_key", sa.String(length=128), nullable=True))
    op.create_index("ix_video_jobs_idempotency_key", "video_jobs", ["idempotency_key"])
    op.create_index(
        "ix_video_jobs_idempotency_key_unique",
        "video_jobs",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_video_jobs_idempotency_key_unique", table_name="video_jobs")
    op.drop_index("ix_video_jobs_idempotency_key", table_name="video_jobs")
    op.drop_column("video_jobs", "idempotency_key")
