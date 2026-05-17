"""Single-instance stuck job reconciler.

Only one reconciler should run in local Compose. Running multiple instances can race
and duplicate recovery attempts; production needs leader election or a distributed lock.
"""

import time

from prometheus_client import start_http_server

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.metrics import (
    RECONCILER_JOBS_INSPECTED_TOTAL,
    RECONCILER_JOBS_RECOVERED_TOTAL,
    RECONCILER_LAST_RUN_DURATION_SECONDS,
    RECONCILER_LAST_RUN_TIMESTAMP_SECONDS,
    RECONCILER_RUNS_TOTAL,
)
from app.core.tracing import configure_tracing, start_span
from app.db.session import SessionLocal
from app.services.job_recovery_service import JobRecoveryService

configure_logging(log_level=settings.log_level, log_json=settings.log_json)
log = get_logger(__name__)


def _record_recovery_outcomes(outcomes: dict[str, int]) -> None:
    for outcome in ("requeued", "failed", "skipped", "enqueue_failed"):
        count = outcomes.get(outcome, 0)
        if count:
            RECONCILER_JOBS_RECOVERED_TOTAL.labels(outcome=outcome).inc(count)


def run_once() -> None:
    start = time.perf_counter()
    db = SessionLocal()
    try:
        with start_span(
            "workers.run_reconciler",
            "reconciler_loop",
            attributes={"reconciler.oneshot": settings.reconciler_oneshot},
        ) as span:
            service = JobRecoveryService()
            if not settings.reconciler_enabled:
                stuck = service.find_stuck_jobs(db)
                RECONCILER_JOBS_INSPECTED_TOTAL.inc(len(stuck))
                RECONCILER_RUNS_TOTAL.labels(outcome="disabled").inc()
                span.set_attribute("inspected_count", len(stuck))
                span.set_attribute("recovered_count", 0)
                span.set_attribute("failed_count", 0)
                span.set_attribute("skipped_count", len(stuck))
                log.info("reconciler_disabled", inspected_count=len(stuck))
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
        duration = time.perf_counter() - start
        RECONCILER_LAST_RUN_DURATION_SECONDS.set(duration)
        RECONCILER_LAST_RUN_TIMESTAMP_SECONDS.set(time.time())
        db.close()


def main() -> None:
    configure_tracing(settings.otel_service_name)
    start_http_server(settings.reconciler_metrics_port, addr="0.0.0.0")
    log.info(
        "reconciler_metrics_server_started",
        port=settings.reconciler_metrics_port,
        metrics_path="/metrics",
    )

    if settings.reconciler_startup_delay_seconds > 0:
        time.sleep(settings.reconciler_startup_delay_seconds)

    while True:
        run_once()
        if settings.reconciler_oneshot:
            return
        time.sleep(settings.reconciler_interval_seconds)


if __name__ == "__main__":
    main()
