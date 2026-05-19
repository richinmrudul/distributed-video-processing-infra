import pytest
import requests

from tests.integration.conftest import (
    get_assets,
    poll_status_until_terminal,
    upload_video,
    wait_for_api_health,
)


pytestmark = pytest.mark.integration
ADMIN_HEADERS = {"X-Admin-API-Key": "dev-admin-key"}


def test_upload_processes_video_to_completion(base_url, valid_video_path):
    wait_for_api_health(base_url)

    upload_response = upload_video(base_url, valid_video_path)

    assert upload_response.status_code == 201
    upload_body = upload_response.json()
    assert upload_body["status"] == "QUEUED"
    assert upload_body["storage_backend"] == "object"

    final_status = poll_status_until_terminal(base_url, upload_body["id"], timeout_seconds=60)

    assert final_status["status"] == "COMPLETED"
    assert final_status["storage_backend"] == "object"
    assert final_status["raw_object_key"]
    assert final_status["processed_object_key"]
    assert final_status["thumbnail_object_key"]
    assert final_status["processing_duration_seconds"] is not None
    assert final_status["error_message"] is None

    assets_response = get_assets(base_url, upload_body["id"])

    assert assets_response.status_code == 200
    assets = assets_response.json()
    assert assets["raw_url"]
    assert assets["processed_url"]
    assert assets["thumbnail_url"]


def test_bad_video_reaches_failed_retry_exhausted(base_url, bad_video_path):
    wait_for_api_health(base_url)

    upload_response = upload_video(base_url, bad_video_path)

    if upload_response.status_code in (400, 413, 415):
        body = upload_response.json()
        assert "detail" in body
        return

    assert upload_response.status_code == 201
    video_id = upload_response.json()["id"]

    final_status = poll_status_until_terminal(base_url, video_id, timeout_seconds=90)

    assert final_status["status"] == "FAILED"
    assert final_status["attempt_count"] == final_status["max_attempts"]
    assert final_status["retry_exhausted"] is True
    assert final_status["last_error_type"]
    assert final_status["error_message"]
    assert len(final_status["error_message"]) <= 500
    assert "configuration:" not in final_status["error_message"].lower()

    failed_response = requests.get(f"{base_url}/api/v1/jobs/failed", headers=ADMIN_HEADERS, timeout=5)
    failed_response.raise_for_status()
    failed_ids = {item["id"] for item in failed_response.json()["jobs"]}
    assert video_id in failed_ids
