from dataclasses import dataclass

from redis import Redis
from rq import Queue
from rq.worker_registration import get_keys

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import (
    UPLOAD_ADMISSION_QUEUE_DEPTH,
    UPLOAD_ADMISSION_WORKER_COUNT,
    VIDEO_UPLOAD_REJECTIONS_TOTAL,
)
from app.core.tracing import start_span

log = get_logger(__name__)


@dataclass(frozen=True)
class AdmissionDecision:
    allowed: bool
    reason: str | None
    queue_depth: int | None
    worker_count: int | None
    queue_pressure_level: str | None


def _queue_pressure(queue_depth: int) -> str:
    if queue_depth <= 5:
        return "LOW"
    if queue_depth <= 20:
        return "MEDIUM"
    return "HIGH"


class UploadAdmissionController:
    def check_upload_allowed(self) -> AdmissionDecision:
        with start_span("app.admission_control", "upload_admission_check") as span:
            decision = self._check_upload_allowed()
            span.set_attribute("admission.allowed", decision.allowed)
            span.set_attribute("admission.reason", decision.reason or "")
            span.set_attribute("queue.max_depth", settings.max_queue_depth_for_uploads)
            span.set_attribute("worker.min_required", settings.min_available_workers_for_uploads)
            if decision.queue_depth is not None:
                span.set_attribute("queue.depth", decision.queue_depth)
            if decision.worker_count is not None:
                span.set_attribute("worker.count", decision.worker_count)
            return decision

    def _check_upload_allowed(self) -> AdmissionDecision:
        if not settings.upload_admission_control_enabled:
            return AdmissionDecision(
                allowed=True,
                reason="admission_control_disabled",
                queue_depth=None,
                worker_count=None,
                queue_pressure_level=None,
            )

        conn = Redis.from_url(settings.redis_url, decode_responses=False)
        try:
            conn.ping()
            queue = Queue(settings.queue_name, connection=conn)
            queue_depth = len(queue)
            worker_count = len(get_keys(queue))
            UPLOAD_ADMISSION_QUEUE_DEPTH.set(queue_depth)
            UPLOAD_ADMISSION_WORKER_COUNT.set(worker_count)

            if worker_count < settings.min_available_workers_for_uploads:
                return self._reject("insufficient_workers", queue_depth, worker_count)
            if queue_depth >= settings.max_queue_depth_for_uploads:
                return self._reject("queue_backlog_high", queue_depth, worker_count)
            return AdmissionDecision(
                allowed=True,
                reason=None,
                queue_depth=queue_depth,
                worker_count=worker_count,
                queue_pressure_level=_queue_pressure(queue_depth),
            )
        except Exception as exc:
            log.warning("upload_admission_check_failed", error=str(exc))
            UPLOAD_ADMISSION_QUEUE_DEPTH.set(0)
            UPLOAD_ADMISSION_WORKER_COUNT.set(0)
            return self._reject("queue_unavailable", None, None)
        finally:
            conn.close()

    def _reject(
        self,
        reason: str,
        queue_depth: int | None,
        worker_count: int | None,
    ) -> AdmissionDecision:
        VIDEO_UPLOAD_REJECTIONS_TOTAL.labels(
            reason=reason,
            storage_backend=settings.storage_backend,
        ).inc()
        return AdmissionDecision(
            allowed=False,
            reason=reason,
            queue_depth=queue_depth,
            worker_count=worker_count,
            queue_pressure_level=_queue_pressure(queue_depth) if queue_depth is not None else None,
        )
