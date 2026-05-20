from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.db.models import VideoJobStatus
from app.services.job_cleanup_service import (
    JobCleanupService,
    filter_cleanup_candidates,
    is_cleanup_candidate,
)
from app.services.object_storage_service import ObjectStorageError


NOW = datetime(2026, 5, 19, tzinfo=timezone.utc)


def job(**overrides):
    values = {
        "id": "video-1",
        "status": VideoJobStatus.COMPLETED,
        "original_filename": "test.mp4",
        "raw_object_key": "videos/video-1/raw/test.mp4",
        "processed_object_key": "videos/video-1/processed/video-1.mp4",
        "thumbnail_object_key": "videos/video-1/thumbnails/video-1.jpg",
        "raw_path": "s3://raw-videos/videos/video-1/raw/test.mp4",
        "processed_path": "s3://processed-videos/videos/video-1/processed/video-1.mp4",
        "thumbnail_path": "s3://thumbnails/videos/video-1/thumbnails/video-1.jpg",
        "retry_exhausted": False,
        "failed_at": None,
        "processing_completed_at": NOW - timedelta(days=8),
        "created_at": NOW - timedelta(days=8),
        "updated_at": NOW - timedelta(days=8),
        "cleaned_up_at": None,
        "cleanup_error_message": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeStorage:
    def __init__(self, *, fail=False) -> None:
        self.fail = fail
        self.deleted: list[tuple[str, str]] = []

    def delete_object(self, bucket_name: str, object_key: str) -> None:
        if self.fail:
            raise ObjectStorageError("missing object")
        self.deleted.append((bucket_name, object_key))


class FakeDb:
    def __init__(self) -> None:
        self.commits = 0
        self.refreshes = 0
        self.deleted = []

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, item) -> None:
        self.refreshes += 1

    def delete(self, item) -> None:
        self.deleted.append(item.id)


def test_completed_job_older_than_retention_is_candidate():
    old_job = job(status=VideoJobStatus.COMPLETED, processing_completed_at=NOW - timedelta(days=8))

    assert is_cleanup_candidate(old_job, now=NOW, completed_after_days=7, failed_after_days=14)


def test_recent_completed_job_is_not_candidate():
    recent_job = job(status=VideoJobStatus.COMPLETED, processing_completed_at=NOW - timedelta(days=2))

    assert not is_cleanup_candidate(recent_job, now=NOW, completed_after_days=7, failed_after_days=14)


def test_failed_retry_exhausted_job_older_than_retention_is_candidate():
    failed_job = job(
        status=VideoJobStatus.FAILED,
        retry_exhausted=True,
        failed_at=NOW - timedelta(days=15),
        processing_completed_at=None,
    )

    assert is_cleanup_candidate(failed_job, now=NOW, completed_after_days=7, failed_after_days=14)


@pytest.mark.parametrize("status", [VideoJobStatus.QUEUED, VideoJobStatus.PROCESSING])
def test_queued_and_processing_jobs_are_never_candidates(status):
    active_job = job(status=status)

    assert not is_cleanup_candidate(active_job, now=NOW, completed_after_days=0, failed_after_days=0)


def test_batch_size_is_respected():
    jobs = [job(id=f"video-{idx}") for idx in range(3)]

    candidates = filter_cleanup_candidates(
        jobs,
        now=NOW,
        completed_after_days=7,
        failed_after_days=14,
        batch_size=2,
    )

    assert [candidate.video_id for candidate in candidates] == ["video-0", "video-1"]


def test_dry_run_does_not_delete_objects_or_mutate_jobs(monkeypatch):
    old_job = job()
    storage = FakeStorage()
    service = JobCleanupService(object_storage=storage)
    monkeypatch.setattr(service, "_candidate_jobs", lambda db, status_filter, limit: [old_job])

    result = service.cleanup(FakeDb(), dry_run=True, completed_after_days=7, failed_after_days=14)

    assert result.candidate_count == 1
    assert result.cleaned_count == 0
    assert storage.deleted == []
    assert old_job.cleaned_up_at is None
    assert old_job.raw_object_key is not None


def test_cleanup_handles_missing_object_as_noop_when_storage_delete_is_idempotent(monkeypatch):
    old_job = job()
    service = JobCleanupService(object_storage=FakeStorage())
    fake_db = FakeDb()
    monkeypatch.setattr(service, "_candidate_jobs", lambda db, status_filter, limit: [old_job])

    result = service.cleanup(fake_db, dry_run=False, completed_after_days=7, failed_after_days=14)

    assert result.cleaned_count == 1
    assert result.failed_count == 0
    assert old_job.cleaned_up_at is not None


def test_cleanup_marks_job_cleaned_and_clears_object_references(monkeypatch):
    old_job = job()
    storage = FakeStorage()
    fake_db = FakeDb()
    service = JobCleanupService(object_storage=storage)
    monkeypatch.setattr(service, "_candidate_jobs", lambda db, status_filter, limit: [old_job])

    result = service.cleanup(fake_db, dry_run=False, completed_after_days=7, failed_after_days=14)

    assert result.cleaned_count == 1
    assert len(storage.deleted) == 3
    assert old_job.cleaned_up_at is not None
    assert old_job.raw_object_key is None
    assert old_job.processed_object_key is None
    assert old_job.thumbnail_object_key is None
    assert fake_db.deleted == []


def test_cleanup_deletes_db_row_when_enabled(monkeypatch):
    old_job = job()
    fake_db = FakeDb()
    service = JobCleanupService(object_storage=FakeStorage())
    monkeypatch.setattr(service, "_candidate_jobs", lambda db, status_filter, limit: [old_job])

    result = service.cleanup(fake_db, dry_run=False, delete_db_rows=True, completed_after_days=7, failed_after_days=14)

    assert result.cleaned_count == 1
    assert fake_db.deleted == ["video-1"]
    assert old_job.cleaned_up_at is None
