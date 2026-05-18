from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.v1 import videos
from app.core.config import settings


def _request_with_idempotency_header(value: bytes | None) -> Request:
    headers = []
    if value is not None:
        headers.append((b"idempotency-key", value))
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers})


class FakeVideoService:
    def __init__(self, existing=None) -> None:
        self.existing = existing
        self.seen_key: str | None = None

    def get_job_by_idempotency_key(self, db, idempotency_key: str):
        self.seen_key = idempotency_key
        return self.existing


def test_missing_key_treated_as_no_idempotency(monkeypatch):
    monkeypatch.setattr(settings, "upload_idempotency_enabled", True)

    key, existing = videos._check_upload_idempotency(
        request=_request_with_idempotency_header(None),
        db=object(),
        service=FakeVideoService(),
    )

    assert key is None
    assert existing is None


def test_valid_key_is_trimmed_and_accepted(monkeypatch):
    monkeypatch.setattr(settings, "upload_idempotency_enabled", True)
    service = FakeVideoService()

    key, existing = videos._check_upload_idempotency(
        request=_request_with_idempotency_header(b"  demo-key-123  "),
        db=object(),
        service=service,
    )

    assert key == "demo-key-123"
    assert service.seen_key == "demo-key-123"
    assert existing is None


def test_empty_key_rejected(monkeypatch):
    monkeypatch.setattr(settings, "upload_idempotency_enabled", True)

    with pytest.raises(HTTPException) as exc:
        videos._check_upload_idempotency(
            request=_request_with_idempotency_header(b"   "),
            db=object(),
            service=FakeVideoService(),
        )

    assert exc.value.status_code == 400


def test_too_long_key_rejected(monkeypatch):
    monkeypatch.setattr(settings, "upload_idempotency_enabled", True)
    monkeypatch.setattr(settings, "idempotency_key_max_length", 4)

    with pytest.raises(HTTPException):
        videos._check_upload_idempotency(
            request=_request_with_idempotency_header(b"abcde"),
            db=object(),
            service=FakeVideoService(),
        )


def test_existing_key_returns_existing_job_without_logging_raw_key(monkeypatch, caplog):
    monkeypatch.setattr(settings, "upload_idempotency_enabled", True)
    existing = SimpleNamespace(id="video-1")

    key, found = videos._check_upload_idempotency(
        request=_request_with_idempotency_header(b"super-secret-key"),
        db=object(),
        service=FakeVideoService(existing=existing),
    )

    assert key == "super-secret-key"
    assert found is existing
    assert "super-secret-key" not in caplog.text


def test_disabled_idempotency_ignores_key(monkeypatch):
    monkeypatch.setattr(settings, "upload_idempotency_enabled", False)
    service = FakeVideoService(existing=SimpleNamespace(id="video-1"))

    key, existing = videos._check_upload_idempotency(
        request=_request_with_idempotency_header(b"demo-key-123"),
        db=object(),
        service=service,
    )

    assert key is None
    assert existing is None
    assert service.seen_key is None
