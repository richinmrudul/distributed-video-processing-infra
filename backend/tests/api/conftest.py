from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("TRACING_ENABLED", "false")

from app.api.v1 import jobs as jobs_api
from app.api.v1 import videos as videos_api
from app.db.models import VideoJobStatus
from app.db.session import get_db
from app.main import app


def sample_job(**overrides):
    now = datetime(2026, 5, 18, tzinfo=timezone.utc)
    values = {
        "id": "video-1",
        "idempotency_key": None,
        "status": VideoJobStatus.QUEUED,
        "original_filename": "test.mp4",
        "raw_path": "s3://raw-videos/videos/video-1/raw/test.mp4",
        "storage_backend": "object",
        "raw_object_key": "videos/video-1/raw/test.mp4",
        "processed_object_key": None,
        "thumbnail_object_key": None,
        "queue_job_id": "rq-1",
        "attempt_count": 0,
        "max_attempts": 3,
        "processed_path": None,
        "thumbnail_path": None,
        "error_message": None,
        "failed_at": None,
        "last_error_type": None,
        "retry_exhausted": False,
        "manually_retried_at": None,
        "manual_retry_count": 0,
        "processing_started_at": None,
        "processing_completed_at": None,
        "processing_duration_seconds": None,
        "cleaned_up_at": None,
        "cleanup_error_message": None,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class ScalarResult:
    def __init__(self, value) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeDb:
    def __init__(self, selected=None) -> None:
        self.selected = selected

    def execute(self, stmt):
        return ScalarResult(self.selected)


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides.clear()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def override_db():
    def _override(selected=None) -> FakeDb:
        db = FakeDb(selected=selected)
        app.dependency_overrides[get_db] = lambda: db
        return db

    return _override


@pytest.fixture
def override_video_deps():
    def _override(*, service, rate_limiter, admission, validator) -> None:
        app.dependency_overrides[videos_api.get_video_service] = lambda: service
        app.dependency_overrides[videos_api.get_upload_rate_limiter] = lambda: rate_limiter
        app.dependency_overrides[videos_api.get_upload_admission_controller] = lambda: admission
        app.dependency_overrides[videos_api.get_upload_validator] = lambda: validator

    return _override


@pytest.fixture
def override_job_service():
    def _override(service) -> None:
        app.dependency_overrides[jobs_api.get_job_service] = lambda: service

    return _override


@pytest.fixture
def override_recovery_service():
    def _override(service) -> None:
        app.dependency_overrides[jobs_api.get_job_recovery_service] = lambda: service

    return _override


@pytest.fixture
def override_cleanup_service():
    def _override(service) -> None:
        app.dependency_overrides[jobs_api.get_job_cleanup_service] = lambda: service

    return _override
