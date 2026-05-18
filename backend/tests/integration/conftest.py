from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest
import requests


DEFAULT_BASE_URL = "http://localhost:8000"
TERMINAL_STATUSES = {"COMPLETED", "FAILED"}


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: tests that require Docker Compose services")


@pytest.fixture(scope="session")
def base_url() -> str:
    return os.environ.get("TEST_API_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


@pytest.fixture(scope="session")
def valid_video_path(tmp_path_factory) -> Path:
    configured = os.environ.get("TEST_VIDEO_PATH")
    if configured:
        path = Path(configured)
        if not path.exists():
            pytest.skip(f"TEST_VIDEO_PATH does not exist: {path}")
        return path

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not found and TEST_VIDEO_PATH is not set")

    out = tmp_path_factory.mktemp("video-fixtures") / "generated_test.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x120:d=1",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(out),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return out


@pytest.fixture
def bad_video_path(tmp_path) -> Path:
    path = tmp_path / "bad.mp4"
    path.write_text("this is not a real video", encoding="utf-8")
    return path


def wait_for_api_health(base_url: str, timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = requests.get(f"{base_url}/health", timeout=2)
            if response.status_code == 200:
                return
        except requests.RequestException as exc:
            last_error = exc
        time.sleep(1)
    if last_error is not None:
        raise AssertionError(f"API did not become healthy: {last_error}") from last_error
    raise AssertionError("API did not become healthy")


def upload_video(base_url: str, file_path: Path, idempotency_key: str | None = None) -> requests.Response:
    headers = {}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    with file_path.open("rb") as fh:
        return requests.post(
            f"{base_url}/api/v1/videos/upload",
            headers=headers,
            files={"file": (file_path.name, fh, "video/mp4")},
            timeout=15,
        )


def get_status(base_url: str, video_id: str) -> dict:
    response = requests.get(f"{base_url}/api/v1/videos/{video_id}/status", timeout=5)
    response.raise_for_status()
    return response.json()


def poll_status_until_terminal(base_url: str, video_id: str, timeout_seconds: int = 60) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last_status: dict | None = None
    while time.monotonic() < deadline:
        last_status = get_status(base_url, video_id)
        if last_status["status"] in TERMINAL_STATUSES:
            return last_status
        time.sleep(1)
    raise AssertionError(f"Job {video_id} did not reach terminal status; last status: {last_status}")


def get_assets(base_url: str, video_id: str) -> requests.Response:
    return requests.get(f"{base_url}/api/v1/videos/{video_id}/assets", timeout=5)


def unique_idempotency_key(prefix: str = "integration-key") -> str:
    return f"{prefix}-{uuid.uuid4()}"
