from app.db.models import VideoJobStatus
from tests.api.conftest import sample_job


def test_health_endpoint_is_public_without_admin_key(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_assets_endpoint_is_public_without_admin_key(client, override_db, monkeypatch):
    from app.api.v1 import videos
    from tests.api.test_video_read_api import FakeObjectStorageService

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
    assert response.json()["video_id"] == "video-1"


def test_openapi_tags_clarify_public_and_admin_boundaries(client):
    schema = client.get("/openapi.json").json()
    tag_names = {tag["name"] for tag in schema["tags"]}

    assert {"Health", "Videos", "Queue", "Storage", "Admin Jobs"}.issubset(tag_names)
    assert schema["paths"]["/api/v1/jobs/failed"]["get"]["tags"] == ["Admin Jobs"]
    assert schema["paths"]["/api/v1/videos/upload"]["post"]["tags"] == ["Videos"]
    assert schema["paths"]["/health"]["get"]["tags"] == ["Health"]
