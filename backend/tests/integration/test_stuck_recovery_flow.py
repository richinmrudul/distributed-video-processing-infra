import os
import subprocess
import time

import pytest

from tests.integration.conftest import get_status, poll_status_until_terminal, upload_video, wait_for_api_health


pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.environ.get("RUN_STUCK_RECOVERY_INTEGRATION") != "1",
    reason="set RUN_STUCK_RECOVERY_INTEGRATION=1 to run the longer reconciler recovery test",
)
def test_automated_reconciler_recovers_stale_processing_job(base_url, valid_video_path):
    wait_for_api_health(base_url)
    upload_response = upload_video(base_url, valid_video_path)
    assert upload_response.status_code == 201
    video_id = upload_response.json()["id"]
    completed = poll_status_until_terminal(base_url, video_id, timeout_seconds=60)
    assert completed["status"] == "COMPLETED"
    original_queue_job_id = completed["queue_job_id"]

    sql = f"""
    UPDATE video_jobs
    SET status='PROCESSING',
        processing_started_at=now() - interval '10 minutes',
        updated_at=now() - interval '10 minutes',
        processed_object_key=NULL,
        thumbnail_object_key=NULL,
        processed_path=NULL,
        thumbnail_path=NULL,
        processing_completed_at=NULL,
        processing_duration_seconds=NULL,
        error_message=NULL,
        retry_exhausted=false
    WHERE id='{video_id}';
    """
    subprocess.run(
        ["docker", "compose", "exec", "-T", "db", "psql", "-U", "video", "-d", "video", "-c", sql],
        check=True,
        stdout=subprocess.DEVNULL,
    )

    deadline = time.monotonic() + 100
    observed_requeue = False
    while time.monotonic() < deadline:
        status = get_status(base_url, video_id)
        if status.get("queue_job_id") and status["queue_job_id"] != original_queue_job_id:
            observed_requeue = True
        if observed_requeue and status["status"] == "COMPLETED":
            assert status["processed_object_key"]
            assert status["thumbnail_object_key"]
            return
        time.sleep(2)
    raise AssertionError("reconciler did not requeue and complete stale processing job")
