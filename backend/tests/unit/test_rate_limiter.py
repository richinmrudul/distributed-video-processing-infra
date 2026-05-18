import pytest
from freezegun import freeze_time

from app.core.config import settings
from app.services import rate_limiter
from app.services.rate_limiter import UploadRateLimiter


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.expired: dict[str, int] = {}
        self.closed = False

    def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, key: str, seconds: int) -> None:
        self.expired[key] = seconds

    def close(self) -> None:
        self.closed = True


class FailingRedis(FakeRedis):
    def incr(self, key: str) -> int:
        raise RuntimeError("redis unavailable")


@pytest.fixture
def fake_redis(monkeypatch):
    conn = FakeRedis()
    monkeypatch.setattr(rate_limiter.Redis, "from_url", lambda *args, **kwargs: conn)
    return conn


def test_disabled_allows_with_disabled_reason(monkeypatch):
    monkeypatch.setattr(settings, "upload_rate_limit_enabled", False)

    decision = UploadRateLimiter()._check_upload_allowed("1.2.3.4")

    assert decision.allowed
    assert decision.reason == "rate_limit_disabled"


@freeze_time("2026-05-18 00:00:00")
def test_first_request_allowed_and_remaining_decreases(monkeypatch, fake_redis):
    monkeypatch.setattr(settings, "upload_rate_limit_enabled", True)
    monkeypatch.setattr(settings, "upload_rate_limit_max_requests", 3)
    monkeypatch.setattr(settings, "upload_rate_limit_window_seconds", 60)

    decision = UploadRateLimiter()._check_upload_allowed("1.2.3.4")

    assert decision.allowed
    assert decision.remaining == 2
    assert decision.reset_seconds >= 0


@freeze_time("2026-05-18 00:00:00")
def test_within_limit_allowed_then_over_limit_rejected(monkeypatch, fake_redis):
    monkeypatch.setattr(settings, "upload_rate_limit_enabled", True)
    monkeypatch.setattr(settings, "upload_rate_limit_max_requests", 2)
    monkeypatch.setattr(settings, "upload_rate_limit_window_seconds", 60)
    limiter = UploadRateLimiter()

    first = limiter._check_upload_allowed("1.2.3.4")
    second = limiter._check_upload_allowed("1.2.3.4")
    third = limiter._check_upload_allowed("1.2.3.4")

    assert first.allowed
    assert second.allowed
    assert second.remaining == 0
    assert not third.allowed
    assert third.reason == "rate_limited"


def test_redis_failure_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "upload_rate_limit_enabled", True)
    monkeypatch.setattr(rate_limiter.Redis, "from_url", lambda *args, **kwargs: FailingRedis())

    decision = UploadRateLimiter()._check_upload_allowed("1.2.3.4")

    assert not decision.allowed
    assert decision.reason == "rate_limiter_unavailable"
