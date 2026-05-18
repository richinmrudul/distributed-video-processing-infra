from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.core.config import settings
from app.db.models import VideoJobStatus
from app.services.job_recovery_service import (
    processing_stuck_age_seconds,
    queued_stuck_age_seconds,
    should_fail_stuck_job,
)


def _job(**kwargs):
    defaults = {
        "status": VideoJobStatus.PROCESSING,
        "processing_started_at": None,
        "updated_at": datetime.now(timezone.utc),
        "attempt_count": 0,
        "max_attempts": 3,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_processing_older_than_timeout_is_stuck(monkeypatch):
    now = datetime(2026, 5, 18, tzinfo=timezone.utc)
    monkeypatch.setattr(settings, "stuck_processing_timeout_seconds", 300)
    job = _job(processing_started_at=now - timedelta(seconds=301))

    assert processing_stuck_age_seconds(job, now) == 301


def test_processing_newer_than_timeout_is_not_stuck(monkeypatch):
    now = datetime(2026, 5, 18, tzinfo=timezone.utc)
    monkeypatch.setattr(settings, "stuck_processing_timeout_seconds", 300)
    job = _job(processing_started_at=now - timedelta(seconds=299))

    assert processing_stuck_age_seconds(job, now) is None


def test_queued_older_than_timeout_is_stuck(monkeypatch):
    now = datetime(2026, 5, 18, tzinfo=timezone.utc)
    monkeypatch.setattr(settings, "stuck_queued_timeout_seconds", 300)
    job = _job(status=VideoJobStatus.QUEUED, updated_at=now - timedelta(seconds=301))

    assert queued_stuck_age_seconds(job, now) == 301


def test_attempt_count_below_max_should_requeue():
    assert not should_fail_stuck_job(_job(attempt_count=2, max_attempts=3))


def test_attempt_count_at_max_should_fail():
    assert should_fail_stuck_job(_job(attempt_count=3, max_attempts=3))
