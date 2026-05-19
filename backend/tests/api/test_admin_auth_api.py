from app.db.models import VideoJobStatus
from tests.api.conftest import sample_job
from tests.api.test_jobs_api import FakeJobService


ADMIN_HEADERS = {"X-Admin-API-Key": "dev-admin-key"}


def test_failed_jobs_without_key_returns_401(client, override_db, override_job_service):
    override_db()
    override_job_service(FakeJobService())

    response = client.get("/api/v1/jobs/failed")

    assert response.status_code == 401
    assert response.json()["detail"] == "Admin API key required"


def test_failed_jobs_with_wrong_key_returns_403(client, override_db, override_job_service):
    override_db()
    override_job_service(FakeJobService())

    response = client.get("/api/v1/jobs/failed", headers={"X-Admin-API-Key": "wrong"})

    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid admin API key"


def test_failed_jobs_with_correct_key_returns_200(client, override_db, override_job_service):
    override_db()
    override_job_service(FakeJobService(failed_jobs=[]))

    response = client.get("/api/v1/jobs/failed", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_retry_without_key_returns_401(client, override_db, override_job_service):
    override_db()
    override_job_service(FakeJobService())

    response = client.post("/api/v1/jobs/video-1/retry")

    assert response.status_code == 401


def test_stuck_jobs_without_key_returns_401(client, override_db):
    override_db()

    response = client.get("/api/v1/jobs/stuck")

    assert response.status_code == 401


def test_recover_stuck_jobs_without_key_returns_401(client, override_db):
    override_db()

    response = client.post("/api/v1/jobs/recover-stuck")

    assert response.status_code == 401


def test_status_endpoint_still_public_without_admin_key(client, override_db):
    override_db(sample_job(id="video-1", status=VideoJobStatus.COMPLETED))

    response = client.get("/api/v1/videos/video-1/status")

    assert response.status_code == 200
    assert response.json()["id"] == "video-1"
