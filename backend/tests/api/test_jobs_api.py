from app.db.models import VideoJobStatus
from app.schemas.jobs import RecoveryResultResponse, StuckJobResponse
from app.services.job_cleanup_service import CleanupCandidate, CleanupResult
from app.services.job_service import JobNotFoundError, JobRetryConflictError
from tests.api.conftest import sample_job


ADMIN_HEADERS = {"X-Admin-API-Key": "dev-admin-key"}


class FakeJobService:
    def __init__(self, *, failed_jobs=None, retry_result=None, retry_error: Exception | None = None) -> None:
        self.failed_jobs = failed_jobs or []
        self.retry_result = retry_result
        self.retry_error = retry_error
        self.list_failed_calls = 0

    def list_failed_jobs(self, db, *, limit=20, retry_exhausted=None):
        self.list_failed_calls += 1
        return self.failed_jobs[:limit]

    def retry_failed_job(self, db, video_id: str):
        if self.retry_error is not None:
            raise self.retry_error
        return self.retry_result


class FakeRecoveryService:
    def __init__(self, *, stuck_jobs=None, recovery_result=None) -> None:
        self.stuck_jobs = stuck_jobs or []
        self.recovery_result = recovery_result or RecoveryResultResponse(
            inspected_count=0,
            recovered_count=0,
            failed_count=0,
            skipped_count=0,
            recovered_job_ids=[],
            failed_job_ids=[],
            skipped_job_ids=[],
        )

    def find_stuck_jobs(self, db):
        return self.stuck_jobs

    def recover_stuck_jobs(self, db):
        return self.recovery_result


class FakeCleanupService:
    def __init__(self, *, candidates=None, cleanup_result=None) -> None:
        self.candidates = candidates or []
        self.cleanup_result = cleanup_result
        self.find_calls = 0
        self.cleanup_calls = []

    def find_cleanup_candidates(self, db, **kwargs):
        self.find_calls += 1
        self.find_kwargs = kwargs
        return self.candidates

    def cleanup(self, db, **kwargs):
        self.cleanup_calls.append(kwargs)
        return self.cleanup_result or CleanupResult(
            dry_run=kwargs.get("dry_run", True),
            inspected_count=len(self.candidates),
            candidate_count=len(self.candidates),
            cleaned_count=0,
            failed_count=0,
            skipped_count=0,
            candidates=self.candidates,
            cleaned_job_ids=[],
            failures=[],
        )


def test_failed_jobs_returns_list(client, override_db, override_job_service):
    job = sample_job(
        id="failed-1",
        status=VideoJobStatus.FAILED,
        retry_exhausted=True,
        last_error_type="ProcessingError",
        error_message="bad video",
    )
    service = FakeJobService(failed_jobs=[job])
    override_db()
    override_job_service(service)

    response = client.get("/api/v1/jobs/failed", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["jobs"][0]["id"] == "failed-1"
    assert service.list_failed_calls == 1


def test_retry_failed_job_returns_queued_response(client, override_db, override_job_service):
    queued = sample_job(
        id="failed-1",
        status=VideoJobStatus.QUEUED,
        queue_job_id="retry-rq-1",
        manual_retry_count=1,
    )
    override_db()
    override_job_service(FakeJobService(retry_result=queued))

    response = client.post("/api/v1/jobs/failed-1/retry", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    assert response.json()["status"] == VideoJobStatus.QUEUED.value
    assert response.json()["queue_job_id"] == "retry-rq-1"


def test_retry_missing_job_returns_404(client, override_db, override_job_service):
    override_db()
    override_job_service(FakeJobService(retry_error=JobNotFoundError("missing")))

    response = client.post("/api/v1/jobs/missing/retry", headers=ADMIN_HEADERS)

    assert response.status_code == 404


def test_retry_completed_job_returns_409(client, override_db, override_job_service):
    override_db()
    override_job_service(FakeJobService(retry_error=JobRetryConflictError("Job already completed")))

    response = client.post("/api/v1/jobs/video-1/retry", headers=ADMIN_HEADERS)

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "retry_not_allowed"


def test_stuck_jobs_returns_list(client, override_db, override_recovery_service):
    stuck = StuckJobResponse(
        id="stuck-1",
        status=VideoJobStatus.PROCESSING,
        original_filename="test.mp4",
        storage_backend="object",
        queue_job_id="rq-1",
        attempt_count=1,
        max_attempts=3,
        retry_exhausted=False,
        processing_started_at=sample_job().created_at,
        created_at=sample_job().created_at,
        updated_at=sample_job().updated_at,
        age_seconds=301,
        stuck_reason="processing_timeout",
    )
    override_db()
    override_recovery_service(FakeRecoveryService(stuck_jobs=[stuck]))

    response = client.get("/api/v1/jobs/stuck", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["jobs"][0]["stuck_reason"] == "processing_timeout"


def test_stuck_jobs_empty_returns_count_zero(client, override_db, override_recovery_service):
    override_db()
    override_recovery_service(FakeRecoveryService(stuck_jobs=[]))

    response = client.get("/api/v1/jobs/stuck", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_recover_stuck_jobs_returns_counts(client, override_db, override_recovery_service):
    result = RecoveryResultResponse(
        inspected_count=3,
        recovered_count=1,
        failed_count=1,
        skipped_count=1,
        recovered_job_ids=["requeued-1"],
        failed_job_ids=["failed-1"],
        skipped_job_ids=["skipped-1"],
    )
    override_db()
    override_recovery_service(FakeRecoveryService(recovery_result=result))

    response = client.post("/api/v1/jobs/recover-stuck", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    assert response.json()["inspected_count"] == 3
    assert response.json()["recovered_count"] == 1


def test_recover_stuck_jobs_disabled_returns_409(client, override_db, override_recovery_service, monkeypatch):
    from app.api.v1 import jobs

    override_db()
    override_recovery_service(FakeRecoveryService())
    monkeypatch.setattr(jobs.settings, "stuck_job_recovery_enabled", False)

    response = client.post("/api/v1/jobs/recover-stuck", headers=ADMIN_HEADERS)

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "stuck_job_recovery_disabled"


def test_cleanup_candidates_requires_admin_key(client):
    response = client.get("/api/v1/jobs/cleanup-candidates")

    assert response.status_code == 401


def test_cleanup_candidates_returns_candidates_with_correct_key(client, override_db, override_cleanup_service):
    candidate = CleanupCandidate(
        video_id="old-1",
        status="COMPLETED",
        original_filename="old.mp4",
        raw_object_key="videos/old-1/raw/old.mp4",
        processed_object_key="videos/old-1/processed/old-1.mp4",
        thumbnail_object_key="videos/old-1/thumbnails/old-1.jpg",
        age_seconds=700000,
        reason="completed_retention_expired",
    )
    service = FakeCleanupService(candidates=[candidate])
    override_db()
    override_cleanup_service(service)

    response = client.get("/api/v1/jobs/cleanup-candidates", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["candidates"][0]["video_id"] == "old-1"
    assert service.find_calls == 1


def test_cleanup_dry_run_returns_candidates_without_mutating(client, override_db, override_cleanup_service):
    candidate = CleanupCandidate(
        video_id="old-1",
        status="FAILED",
        original_filename="bad.mp4",
        raw_object_key="videos/old-1/raw/bad.mp4",
        processed_object_key=None,
        thumbnail_object_key=None,
        age_seconds=1400000,
        reason="failed_retention_expired",
    )
    service = FakeCleanupService(candidates=[candidate])
    override_db()
    override_cleanup_service(service)

    response = client.post("/api/v1/jobs/cleanup?dry_run=true", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    assert response.json()["dry_run"] is True
    assert response.json()["candidate_count"] == 1
    assert response.json()["cleaned_count"] == 0
    assert service.cleanup_calls[0]["dry_run"] is True


def test_cleanup_actual_requires_correct_admin_key(client):
    response = client.post("/api/v1/jobs/cleanup?dry_run=false", headers={"X-Admin-API-Key": "wrong"})

    assert response.status_code == 403


def test_cleanup_actual_returns_cleaned_ids(client, override_db, override_cleanup_service):
    result = CleanupResult(
        dry_run=False,
        inspected_count=1,
        candidate_count=1,
        cleaned_count=1,
        failed_count=0,
        skipped_count=0,
        candidates=[],
        cleaned_job_ids=["old-1"],
        failures=[],
    )
    service = FakeCleanupService(cleanup_result=result)
    override_db()
    override_cleanup_service(service)

    response = client.post("/api/v1/jobs/cleanup?dry_run=false", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    assert response.json()["dry_run"] is False
    assert response.json()["cleaned_job_ids"] == ["old-1"]
    assert service.cleanup_calls[0]["dry_run"] is False
