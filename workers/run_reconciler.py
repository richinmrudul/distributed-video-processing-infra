"""Stuck job reconciler.

The recovery pass is guarded by a Redis lock so scaled local reconcilers do not
recover the same jobs concurrently.
"""

import time
import uuid

from prometheus_client import start_http_server

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.metrics import (
    RECONCILER_JOBS_INSPECTED_TOTAL,
    RECONCILER_JOBS_RECOVERED_TOTAL,
    RECONCILER_LAST_RUN_DURATION_SECONDS,
    RECONCILER_LAST_RUN_TIMESTAMP_SECONDS,
    RECONCILER_LOCK_ACQUIRE_TOTAL,
    RECONCILER_LOCK_HELD,
    RECONCILER_LOCK_RELEASE_TOTAL,
    RECONCILER_RUNS_TOTAL,
    initialize_reconciler_lock_metrics,
)
from app.core.tracing import configure_tracing, start_span
from app.db.session import SessionLocal
from app.services.distributed_lock import RedisDistributedLock
from app.services.job_recovery_service import JobRecoveryService

configure_logging(log_level=settings.log_level, log_json=settings.log_json)
log = get_logger(__name__)


def _record_recovery_outcomes(outcomes: dict[str, int]) -> None:
    for outcome in ("requeued", "failed", "skipped", "enqueue_failed"):
        count = outcomes.get(outcome, 0)
        if count:
            RECONCILER_JOBS_RECOVERED_TOTAL.labels(outcome=outcome).inc(count)


def _hold_lock_for_interval(start: float) -> None:
    if settings.reconciler_oneshot:
        return
    # Keep the lease for most of the interval so staggered reconcilers skip this cycle.
    hold_seconds = min(
        settings.reconciler_interval_seconds,
        max(0, settings.reconciler_lock_ttl_seconds - 1),
    )
    remaining = hold_seconds - (time.perf_counter() - start)
    if remaining > 0:
        time.sleep(remaining)


def _acquire_reconciler_lock(run_id: str) -> RedisDistributedLock | None:
    if not settings.reconciler_lock_enabled:
        RECONCILER_LOCK_ACQUIRE_TOTAL.labels(outcome="disabled").inc()
        RECONCILER_LOCK_HELD.set(0)
        return None

    lock = RedisDistributedLock(
        key=settings.reconciler_lock_key,
        ttl_seconds=settings.reconciler_lock_ttl_seconds,
        acquire_timeout_seconds=settings.reconciler_lock_acquire_timeout_seconds,
    )
    with start_span(
        "workers.run_reconciler",
        "reconciler_acquire_lock",
        attributes={
            "lock.enabled": True,
            "lock.key": settings.reconciler_lock_key,
            "lock.ttl_seconds": settings.reconciler_lock_ttl_seconds,
        },
    ) as span:
        acquired = lock.acquire()
        span.set_attribute("lock.acquired", acquired)
        if acquired:
            RECONCILER_LOCK_ACQUIRE_TOTAL.labels(outcome="acquired").inc()
            RECONCILER_LOCK_HELD.set(1)
            log.info(
                "reconciler_lock_acquired",
                lock_key=settings.reconciler_lock_key,
                ttl_seconds=settings.reconciler_lock_ttl_seconds,
                run_id=run_id,
            )
            return lock
        RECONCILER_LOCK_HELD.set(0)
        if lock.last_error:
            RECONCILER_LOCK_ACQUIRE_TOTAL.labels(outcome="error").inc()
        else:
            RECONCILER_LOCK_ACQUIRE_TOTAL.labels(outcome="skipped").inc()
        log.info(
            "reconciler_lock_not_acquired",
            lock_key=settings.reconciler_lock_key,
            ttl_seconds=settings.reconciler_lock_ttl_seconds,
            run_id=run_id,
            error=lock.last_error,
        )
        lock.close()
        return None


def _release_reconciler_lock(lock: RedisDistributedLock | None, run_id: str) -> None:
    if not settings.reconciler_lock_enabled:
        RECONCILER_LOCK_RELEASE_TOTAL.labels(outcome="skipped").inc()
        RECONCILER_LOCK_HELD.set(0)
        return
    if lock is None:
        RECONCILER_LOCK_RELEASE_TOTAL.labels(outcome="skipped").inc()
        RECONCILER_LOCK_HELD.set(0)
        return

    with start_span(
        "workers.run_reconciler",
        "reconciler_release_lock",
        attributes={
            "lock.enabled": True,
            "lock.key": settings.reconciler_lock_key,
            "lock.ttl_seconds": settings.reconciler_lock_ttl_seconds,
        },
    ) as span:
        released = lock.release()
        span.set_attribute("lock.release_success", released)
        RECONCILER_LOCK_HELD.set(0)
        if released:
            RECONCILER_LOCK_RELEASE_TOTAL.labels(outcome="released").inc()
            log.info(
                "reconciler_lock_released",
                lock_key=settings.reconciler_lock_key,
                ttl_seconds=settings.reconciler_lock_ttl_seconds,
                run_id=run_id,
            )
            return
        RECONCILER_LOCK_RELEASE_TOTAL.labels(outcome="failed").inc()
        log.warning(
            "reconciler_lock_release_failed",
            lock_key=settings.reconciler_lock_key,
            ttl_seconds=settings.reconciler_lock_ttl_seconds,
            run_id=run_id,
            error=lock.last_error,
        )


def run_once() -> None:
    run_id = str(uuid.uuid4())
    start = time.perf_counter()
    db = SessionLocal()
    lock: RedisDistributedLock | None = None
    try:
        with start_span(
            "workers.run_reconciler",
            "reconciler_loop",
            attributes={"reconciler.oneshot": settings.reconciler_oneshot},
        ) as span:
            service = JobRecoveryService()
            if not settings.reconciler_enabled:
                RECONCILER_LOCK_ACQUIRE_TOTAL.labels(outcome="disabled").inc()
                RECONCILER_LOCK_HELD.set(0)
                stuck = service.find_stuck_jobs(db)
                RECONCILER_JOBS_INSPECTED_TOTAL.inc(len(stuck))
                RECONCILER_RUNS_TOTAL.labels(outcome="disabled").inc()
                span.set_attribute("inspected_count", len(stuck))
                span.set_attribute("recovered_count", 0)
                span.set_attribute("failed_count", 0)
                span.set_attribute("skipped_count", len(stuck))
                log.info("reconciler_disabled", inspected_count=len(stuck))
                return

            lock = _acquire_reconciler_lock(run_id)
            if settings.reconciler_lock_enabled and lock is None:
                span.set_attribute("recovery.outcome", "lock_not_acquired")
                RECONCILER_RUNS_TOTAL.labels(outcome="lock_skipped").inc()
                return

            if not settings.stuck_job_recovery_enabled:
                stuck = service.find_stuck_jobs(db)
                RECONCILER_JOBS_INSPECTED_TOTAL.inc(len(stuck))
                RECONCILER_RUNS_TOTAL.labels(outcome="disabled").inc()
                span.set_attribute("inspected_count", len(stuck))
                span.set_attribute("recovered_count", 0)
                span.set_attribute("failed_count", 0)
                span.set_attribute("skipped_count", len(stuck))
                log.info("stuck_job_recovery_disabled", inspected_count=len(stuck))
                return

            result = service.recover_stuck_jobs(db)
            RECONCILER_JOBS_INSPECTED_TOTAL.inc(result.inspected_count)
            _record_recovery_outcomes(service.last_recovery_outcomes)
            RECONCILER_RUNS_TOTAL.labels(outcome="success").inc()
            span.set_attribute("inspected_count", result.inspected_count)
            span.set_attribute("recovered_count", result.recovered_count)
            span.set_attribute("failed_count", result.failed_count)
            span.set_attribute("skipped_count", result.skipped_count)
            log.info(
                "reconciler_run_finished",
                inspected_count=result.inspected_count,
                recovered_count=result.recovered_count,
                failed_count=result.failed_count,
                skipped_count=result.skipped_count,
            )
    except Exception as exc:
        db.rollback()
        RECONCILER_RUNS_TOTAL.labels(outcome="error").inc()
        log.exception("reconciler_run_failed", error=str(exc))
    finally:
        if lock is not None and lock.acquired:
            _hold_lock_for_interval(start)
        _release_reconciler_lock(lock, run_id)
        duration = time.perf_counter() - start
        RECONCILER_LAST_RUN_DURATION_SECONDS.set(duration)
        RECONCILER_LAST_RUN_TIMESTAMP_SECONDS.set(time.time())
        db.close()


def main() -> None:
    configure_tracing(settings.otel_service_name)
    initialize_reconciler_lock_metrics()
    start_http_server(settings.reconciler_metrics_port, addr="0.0.0.0")
    log.info(
        "reconciler_metrics_server_started",
        port=settings.reconciler_metrics_port,
        metrics_path="/metrics",
    )

    if settings.reconciler_startup_delay_seconds > 0:
        time.sleep(settings.reconciler_startup_delay_seconds)

    while True:
        loop_start = time.perf_counter()
        run_once()
        if settings.reconciler_oneshot:
            return
        time.sleep(max(0, settings.reconciler_interval_seconds - (time.perf_counter() - loop_start)))


if __name__ == "__main__":
    main()
