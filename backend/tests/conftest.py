from __future__ import annotations

import io
from pathlib import Path
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


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    requested_paths = [Path(arg).as_posix() for arg in config.args]
    if any(path.endswith("backend/tests/integration") or path.endswith("tests/integration") for path in requested_paths):
        return

    skip_integration = pytest.mark.skip(reason="integration tests require Docker Compose; run backend/tests/integration")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
