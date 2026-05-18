from app.core.config import settings
from app.services import admission_control
from app.services.admission_control import UploadAdmissionController


class FakeRedis:
    def ping(self) -> None:
        return None

    def close(self) -> None:
        return None


class FailingRedis(FakeRedis):
    def ping(self) -> None:
        raise RuntimeError("redis unavailable")


class FakeQueue:
    depth = 0

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __len__(self) -> int:
        return self.depth


def _patch_queue(monkeypatch, *, queue_depth: int, worker_count: int) -> None:
    FakeQueue.depth = queue_depth
    monkeypatch.setattr(admission_control.Redis, "from_url", lambda *args, **kwargs: FakeRedis())
    monkeypatch.setattr(admission_control, "Queue", FakeQueue)
    monkeypatch.setattr(admission_control, "get_keys", lambda queue: [f"worker-{i}" for i in range(worker_count)])


def test_disabled_allows(monkeypatch):
    monkeypatch.setattr(settings, "upload_admission_control_enabled", False)

    decision = UploadAdmissionController()._check_upload_allowed()

    assert decision.allowed
    assert decision.reason == "admission_control_disabled"


def test_redis_unavailable_rejects(monkeypatch):
    monkeypatch.setattr(settings, "upload_admission_control_enabled", True)
    monkeypatch.setattr(admission_control.Redis, "from_url", lambda *args, **kwargs: FailingRedis())

    decision = UploadAdmissionController()._check_upload_allowed()

    assert not decision.allowed
    assert decision.reason == "queue_unavailable"


def test_worker_count_below_min_rejects(monkeypatch):
    monkeypatch.setattr(settings, "upload_admission_control_enabled", True)
    monkeypatch.setattr(settings, "min_available_workers_for_uploads", 2)
    _patch_queue(monkeypatch, queue_depth=0, worker_count=1)

    decision = UploadAdmissionController()._check_upload_allowed()

    assert not decision.allowed
    assert decision.reason == "insufficient_workers"


def test_queue_depth_at_max_rejects(monkeypatch):
    monkeypatch.setattr(settings, "upload_admission_control_enabled", True)
    monkeypatch.setattr(settings, "min_available_workers_for_uploads", 1)
    monkeypatch.setattr(settings, "max_queue_depth_for_uploads", 10)
    _patch_queue(monkeypatch, queue_depth=10, worker_count=1)

    decision = UploadAdmissionController()._check_upload_allowed()

    assert not decision.allowed
    assert decision.reason == "queue_backlog_high"


def test_enough_workers_and_queue_below_max_allows(monkeypatch):
    monkeypatch.setattr(settings, "upload_admission_control_enabled", True)
    monkeypatch.setattr(settings, "min_available_workers_for_uploads", 1)
    monkeypatch.setattr(settings, "max_queue_depth_for_uploads", 10)
    _patch_queue(monkeypatch, queue_depth=9, worker_count=2)

    decision = UploadAdmissionController()._check_upload_allowed()

    assert decision.allowed
    assert decision.reason is None
    assert decision.queue_pressure_level == "MEDIUM"
