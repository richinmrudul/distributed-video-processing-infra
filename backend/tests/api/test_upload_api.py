from app.db.models import VideoJobStatus
from app.services.admission_control import AdmissionDecision
from app.services.rate_limiter import RateLimitDecision
from app.services.upload_validation import UploadValidationDecision
from app.services.video_service import VideoUploadResult
from tests.api.conftest import sample_job


class FakeRateLimiter:
    def __init__(self, decision: RateLimitDecision | None = None) -> None:
        self.decision = decision or RateLimitDecision(True, None, 10, 9, 60, "127.0.0.1")

    def check_upload_allowed(self, request):
        return self.decision


class FakeAdmission:
    def __init__(self, decision: AdmissionDecision | None = None) -> None:
        self.decision = decision or AdmissionDecision(True, None, 0, 3, "LOW")

    def check_upload_allowed(self):
        return self.decision


class FakeValidator:
    def validate_request_metadata(self, request):
        return UploadValidationDecision(True, None, 100, None, None, None)

    def validate_upload_file(self, file):
        return UploadValidationDecision(True, None, 100, None, file.filename, file.content_type)


class FakeVideoService:
    def __init__(self, *, existing=None, created=None) -> None:
        self.existing = existing
        self.created = created or sample_job()
        self.upload_calls = 0
        self.idempotency_lookup_keys: list[str] = []

    def get_job_by_idempotency_key(self, db, idempotency_key: str):
        self.idempotency_lookup_keys.append(idempotency_key)
        return self.existing

    async def upload_and_process(self, db, file, *, idempotency_key=None):
        self.upload_calls += 1
        job = self.created
        job.idempotency_key = idempotency_key
        return VideoUploadResult(job=job, idempotency_outcome="new_key")


def _post_upload(client, *, headers=None):
    return client.post(
        "/api/v1/videos/upload",
        headers=headers or {},
        files={"file": ("test.mp4", b"fake-video", "video/mp4")},
    )


def test_normal_upload_returns_201(client, override_db, override_video_deps):
    service = FakeVideoService(created=sample_job(id="video-new", queue_job_id="rq-new"))
    override_db()
    override_video_deps(
        service=service,
        rate_limiter=FakeRateLimiter(),
        admission=FakeAdmission(),
        validator=FakeValidator(),
    )

    response = _post_upload(client)

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "video-new"
    assert body["status"] == VideoJobStatus.QUEUED.value
    assert body["original_filename"] == "test.mp4"
    assert body["queue_job_id"] == "rq-new"
    assert body["idempotency_key"] is None


def test_first_idempotency_key_upload_returns_201(client, override_db, override_video_deps):
    service = FakeVideoService(created=sample_job(id="video-keyed"))
    override_db()
    override_video_deps(service=service, rate_limiter=FakeRateLimiter(), admission=FakeAdmission(), validator=FakeValidator())

    response = _post_upload(client, headers={"Idempotency-Key": "demo-key-123"})

    assert response.status_code == 201
    assert response.json()["idempotency_key"] == "demo-key-123"
    assert service.upload_calls == 1


def test_duplicate_idempotency_key_returns_200_without_upload_call(client, override_db, override_video_deps):
    existing = sample_job(id="video-existing", idempotency_key="demo-key-123", status=VideoJobStatus.COMPLETED)
    service = FakeVideoService(existing=existing)
    override_db()
    override_video_deps(service=service, rate_limiter=FakeRateLimiter(), admission=FakeAdmission(), validator=FakeValidator())

    response = _post_upload(client, headers={"Idempotency-Key": "demo-key-123"})

    assert response.status_code == 200
    assert response.json()["id"] == "video-existing"
    assert service.upload_calls == 0


def test_empty_idempotency_key_returns_400(client, override_db, override_video_deps):
    override_db()
    override_video_deps(
        service=FakeVideoService(),
        rate_limiter=FakeRateLimiter(),
        admission=FakeAdmission(),
        validator=FakeValidator(),
    )

    response = _post_upload(client, headers={"Idempotency-Key": ""})

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "invalid_idempotency_key"


def test_too_long_idempotency_key_returns_400(client, override_db, override_video_deps):
    override_db()
    override_video_deps(
        service=FakeVideoService(),
        rate_limiter=FakeRateLimiter(),
        admission=FakeAdmission(),
        validator=FakeValidator(),
    )

    response = _post_upload(client, headers={"Idempotency-Key": "x" * 129})

    assert response.status_code == 400


def test_rate_limit_rejection_returns_429(client, override_db, override_video_deps):
    decision = RateLimitDecision(False, "rate_limited", 10, 0, 60, "127.0.0.1")
    override_db()
    override_video_deps(
        service=FakeVideoService(),
        rate_limiter=FakeRateLimiter(decision),
        admission=FakeAdmission(),
        validator=FakeValidator(),
    )

    response = _post_upload(client)

    assert response.status_code == 429
    assert response.json()["detail"]["reason"] == "rate_limited"


def test_admission_insufficient_workers_returns_503(client, override_db, override_video_deps):
    decision = AdmissionDecision(False, "insufficient_workers", 0, 0, "LOW")
    override_db()
    override_video_deps(
        service=FakeVideoService(),
        rate_limiter=FakeRateLimiter(),
        admission=FakeAdmission(decision),
        validator=FakeValidator(),
    )

    response = _post_upload(client)

    assert response.status_code == 503
    assert response.json()["detail"]["reason"] == "insufficient_workers"


def test_admission_queue_backlog_returns_429(client, override_db, override_video_deps):
    decision = AdmissionDecision(False, "queue_backlog_high", 50, 3, "HIGH")
    override_db()
    override_video_deps(
        service=FakeVideoService(),
        rate_limiter=FakeRateLimiter(),
        admission=FakeAdmission(decision),
        validator=FakeValidator(),
    )

    response = _post_upload(client)

    assert response.status_code == 429
    assert response.json()["detail"]["reason"] == "queue_backlog_high"
