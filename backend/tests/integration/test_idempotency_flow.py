import pytest

from tests.integration.conftest import (
    poll_status_until_terminal,
    unique_idempotency_key,
    upload_video,
    wait_for_api_health,
)


pytestmark = pytest.mark.integration


def test_upload_idempotency_returns_existing_job(base_url, valid_video_path):
    wait_for_api_health(base_url)
    key = unique_idempotency_key()

    first_response = upload_video(base_url, valid_video_path, idempotency_key=key)
    second_response = upload_video(base_url, valid_video_path, idempotency_key=key)

    assert first_response.status_code == 201
    assert second_response.status_code == 200

    first_body = first_response.json()
    second_body = second_response.json()
    assert first_body["idempotency_key"] == key
    assert second_body["idempotency_key"] == key
    assert second_body["id"] == first_body["id"]

    final_status = poll_status_until_terminal(base_url, first_body["id"], timeout_seconds=60)
    assert final_status["status"] == "COMPLETED"
