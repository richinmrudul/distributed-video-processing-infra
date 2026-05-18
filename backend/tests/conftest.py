from __future__ import annotations

import io
from types import SimpleNamespace

import pytest


class FakeUploadFile:
    def __init__(
        self,
        *,
        filename: str | None = "video.mp4",
        content_type: str | None = "video/mp4",
        body: bytes = b"video",
    ) -> None:
        self.filename = filename
        self.content_type = content_type
        self.file = io.BytesIO(body)


def fake_request(headers: dict[str, str] | None = None, host: str = "127.0.0.1") -> SimpleNamespace:
    return SimpleNamespace(headers=headers or {}, client=SimpleNamespace(host=host))


@pytest.fixture(autouse=True)
def disable_tracing(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "tracing_enabled", False)
