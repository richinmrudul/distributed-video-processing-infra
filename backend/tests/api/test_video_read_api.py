from app.db.models import VideoJobStatus
from tests.api.conftest import sample_job


class FakeObjectStorageService:
    def generate_presigned_url(self, bucket: str, key: str, expires_in_seconds: int) -> str:
        return f"https://objects.test/{bucket}/{key}?expires={expires_in_seconds}"


def test_status_existing_job_returns_200(client, override_db):
    override_db(sample_job(id="video-1", status=VideoJobStatus.COMPLETED))

    response = client.get("/api/v1/videos/video-1/status")

    assert response.status_code == 200
    assert response.json()["id"] == "video-1"
    assert response.json()["status"] == VideoJobStatus.COMPLETED.value


def test_status_missing_job_returns_404(client, override_db):
    override_db(None)

    response = client.get("/api/v1/videos/missing/status")

    assert response.status_code == 404


def test_assets_completed_object_job_returns_urls(client, override_db, monkeypatch):
    from app.api.v1 import videos

    job = sample_job(
        id="video-1",
        status=VideoJobStatus.COMPLETED,
        storage_backend="object",
        processed_object_key="videos/video-1/processed/video-1.mp4",
        thumbnail_object_key="videos/video-1/thumbnails/video-1.jpg",
    )
    override_db(job)
    monkeypatch.setattr(videos, "ObjectStorageService", FakeObjectStorageService)

    response = client.get("/api/v1/videos/video-1/assets")

    assert response.status_code == 200
    body = response.json()
    assert body["video_id"] == "video-1"
    assert body["raw_url"].startswith("https://objects.test/raw-videos/")
    assert body["processed_url"].startswith("https://objects.test/processed-videos/")
    assert body["thumbnail_url"].startswith("https://objects.test/thumbnails/")


def test_assets_missing_job_returns_404(client, override_db):
    override_db(None)

    response = client.get("/api/v1/videos/missing/assets")

    assert response.status_code == 404


def test_assets_not_completed_returns_409(client, override_db):
    override_db(sample_job(status=VideoJobStatus.QUEUED, storage_backend="object"))

    response = client.get("/api/v1/videos/video-1/assets")

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "assets_not_ready"


def test_assets_local_storage_returns_400(client, override_db):
    override_db(sample_job(status=VideoJobStatus.COMPLETED, storage_backend="local"))

    response = client.get("/api/v1/videos/video-1/assets")

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "unsupported_storage_backend"
