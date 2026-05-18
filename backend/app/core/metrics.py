"""Prometheus metrics for API, queue, storage, and worker instrumentation.

Worker containers set PROMETHEUS_MULTIPROC_DIR; RQ runs each job in a subprocess, and
prometheus_client multiprocess mode aggregates metrics in workers/run_worker.py via
MultiProcessCollector. The API process does not set that env var (default registry).
"""

from prometheus_client import Counter, Gauge, Histogram

# --- HTTP (API process) ---

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)

# --- Video (API upload + worker processing) ---

VIDEO_UPLOADS_TOTAL = Counter(
    "video_uploads_total",
    "Video upload attempts",
    ["storage_backend", "status"],
)

VIDEO_UPLOAD_REJECTIONS_TOTAL = Counter(
    "video_upload_rejections_total",
    "Video uploads rejected by admission control",
    ["reason", "storage_backend"],
)

VIDEO_UPLOAD_RATE_LIMIT_CHECKS_TOTAL = Counter(
    "video_upload_rate_limit_checks_total",
    "Upload rate limit checks",
    ["outcome"],
)

VIDEO_UPLOAD_RATE_LIMIT_REJECTIONS_TOTAL = Counter(
    "video_upload_rate_limit_rejections_total",
    "Uploads rejected by the upload rate limiter",
    ["reason"],
)

UPLOAD_RATE_LIMIT_REMAINING = Gauge(
    "upload_rate_limit_remaining",
    "Remaining upload requests in the current rate limit window",
    ["client_type"],
)

VIDEO_UPLOAD_VALIDATION_CHECKS_TOTAL = Counter(
    "video_upload_validation_checks_total",
    "Upload validation checks",
    ["outcome"],
)

VIDEO_UPLOAD_VALIDATION_REJECTIONS_TOTAL = Counter(
    "video_upload_validation_rejections_total",
    "Uploads rejected by validation",
    ["reason"],
)

VIDEO_UPLOAD_IDEMPOTENCY_REQUESTS_TOTAL = Counter(
    "video_upload_idempotency_requests_total",
    "Upload idempotency checks",
    ["outcome"],
)

VIDEO_UPLOAD_IDEMPOTENCY_HITS_TOTAL = Counter(
    "video_upload_idempotency_hits_total",
    "Upload requests that reused an existing idempotent video job",
)

UPLOAD_VALIDATION_CONTENT_LENGTH_BYTES = Gauge(
    "upload_validation_content_length_bytes",
    "Last observed upload request Content-Length in bytes",
)

UPLOAD_ADMISSION_QUEUE_DEPTH = Gauge(
    "upload_admission_queue_depth",
    "Queue depth observed during upload admission checks",
)

UPLOAD_ADMISSION_WORKER_COUNT = Gauge(
    "upload_admission_worker_count",
    "Worker count observed during upload admission checks",
)

VIDEO_PROCESSING_JOBS_TOTAL = Counter(
    "video_processing_jobs_total",
    "Video processing job outcomes in workers",
    ["status", "storage_backend"],
)

VIDEO_PROCESSING_DURATION_SECONDS = Histogram(
    "video_processing_duration_seconds",
    "Video processing duration in seconds",
    ["storage_backend"],
)

# Processing-layer failure count (each FFmpeg/worker exception).
VIDEO_PROCESSING_FAILURES_TOTAL = Counter(
    "video_processing_failures_total",
    "Video processing failures at the processing layer",
    ["storage_backend", "error_type"],
)

# Job lifecycle failure count (includes intermediate attempts before exhaustion).
VIDEO_JOBS_FAILED_TOTAL = Counter(
    "video_jobs_failed_total",
    "Video job failure events in workers",
    ["storage_backend", "error_type", "retry_exhausted"],
)

VIDEO_MANUAL_RETRIES_TOTAL = Counter(
    "video_manual_retries_total",
    "Manual retries triggered via API",
    ["storage_backend"],
)

VIDEO_RETRY_EXHAUSTED_TOTAL = Counter(
    "video_retry_exhausted_total",
    "Video jobs that exhausted automatic retries",
    ["storage_backend", "error_type"],
)

# Refreshed when GET /api/v1/jobs/failed runs (API scrape only).
FAILED_JOBS_CURRENT = Gauge(
    "failed_jobs_current",
    "Current failed video jobs in Postgres",
    ["storage_backend", "retry_exhausted"],
)

_FAILED_JOBS_GAUGE_BACKENDS = ("local", "object", "unknown")

STUCK_JOBS_CURRENT = Gauge(
    "stuck_jobs_current",
    "Current stuck video jobs in Postgres",
    ["status", "stuck_reason"],
)

STUCK_JOBS_RECOVERED_TOTAL = Counter(
    "stuck_jobs_recovered_total",
    "Stuck job recovery outcomes",
    ["original_status", "outcome"],
)

_STUCK_JOB_STATUSES = ("PROCESSING", "QUEUED")
_STUCK_JOB_REASONS = ("processing_timeout", "queued_timeout")

RECONCILER_RUNS_TOTAL = Counter(
    "reconciler_runs_total",
    "Reconciler loop executions",
    ["outcome"],
)

RECONCILER_JOBS_INSPECTED_TOTAL = Counter(
    "reconciler_jobs_inspected_total",
    "Jobs inspected by the reconciler",
)

RECONCILER_JOBS_RECOVERED_TOTAL = Counter(
    "reconciler_jobs_recovered_total",
    "Stuck job recovery outcomes from the reconciler",
    ["outcome"],
)

RECONCILER_LAST_RUN_TIMESTAMP_SECONDS = Gauge(
    "reconciler_last_run_timestamp_seconds",
    "Unix timestamp of the reconciler's last completed run",
)

RECONCILER_LAST_RUN_DURATION_SECONDS = Gauge(
    "reconciler_last_run_duration_seconds",
    "Duration in seconds of the reconciler's last completed run",
)

RECONCILER_LOCK_ACQUIRE_TOTAL = Counter(
    "reconciler_lock_acquire_total",
    "Reconciler Redis lock acquisition attempts",
    ["outcome"],
)

RECONCILER_LOCK_HELD = Gauge(
    "reconciler_lock_held",
    "Whether this reconciler instance currently holds the Redis lock",
)

RECONCILER_LOCK_RELEASE_TOTAL = Counter(
    "reconciler_lock_release_total",
    "Reconciler Redis lock release attempts",
    ["outcome"],
)


def initialize_reconciler_lock_metrics() -> None:
    """Create zero-valued reconciler lock series before the first lock cycle."""
    for outcome in ("acquired", "skipped", "error", "disabled"):
        RECONCILER_LOCK_ACQUIRE_TOTAL.labels(outcome=outcome)
    for outcome in ("released", "failed", "skipped"):
        RECONCILER_LOCK_RELEASE_TOTAL.labels(outcome=outcome)
    RECONCILER_LOCK_HELD.set(0)

# --- Queue (updated when /api/v1/queue/health runs) ---

QUEUE_DEPTH = Gauge(
    "queue_depth",
    "Jobs waiting in the RQ queue",
    ["queue_name"],
)

QUEUE_WORKERS = Gauge(
    "queue_workers",
    "Registered RQ workers for the queue",
    ["queue_name"],
)

QUEUE_STARTED_JOBS = Gauge(
    "queue_started_jobs",
    "Jobs in the RQ started registry",
    ["queue_name"],
)

QUEUE_FINISHED_JOBS = Gauge(
    "queue_finished_jobs",
    "Jobs in the RQ finished registry",
    ["queue_name"],
)

QUEUE_FAILED_JOBS = Gauge(
    "queue_failed_jobs",
    "Jobs in the RQ failed registry",
    ["queue_name"],
)

# --- Object storage ---

OBJECT_STORAGE_OPERATIONS_TOTAL = Counter(
    "object_storage_operations_total",
    "S3-compatible object storage operations",
    ["operation", "bucket", "status"],
)


def record_object_storage_operation(operation: str, bucket: str, *, success: bool) -> None:
    OBJECT_STORAGE_OPERATIONS_TOTAL.labels(
        operation=operation,
        bucket=bucket or "unknown",
        status="success" if success else "failure",
    ).inc()


def update_queue_gauges(
    *,
    queue_name: str,
    queued: int,
    workers: int,
    started: int,
    finished: int,
    failed: int,
) -> None:
    """Refresh queue gauges from queue health snapshot."""
    QUEUE_DEPTH.labels(queue_name=queue_name).set(queued)
    QUEUE_WORKERS.labels(queue_name=queue_name).set(workers)
    QUEUE_STARTED_JOBS.labels(queue_name=queue_name).set(started)
    QUEUE_FINISHED_JOBS.labels(queue_name=queue_name).set(finished)
    QUEUE_FAILED_JOBS.labels(queue_name=queue_name).set(failed)


def refresh_failed_jobs_gauge(db) -> None:
    """Set failed_jobs_current from Postgres (call from API on /jobs/failed)."""
    from sqlalchemy import func, select

    from app.db.models import VideoJob, VideoJobStatus

    for backend in _FAILED_JOBS_GAUGE_BACKENDS:
        for exhausted in ("true", "false"):
            FAILED_JOBS_CURRENT.labels(storage_backend=backend, retry_exhausted=exhausted).set(0)

    rows = db.execute(
        select(
            VideoJob.storage_backend,
            VideoJob.retry_exhausted,
            func.count(),
        )
        .where(VideoJob.status == VideoJobStatus.FAILED)
        .group_by(VideoJob.storage_backend, VideoJob.retry_exhausted)
    ).all()

    for storage_backend, retry_exhausted, count in rows:
        backend = storage_backend or "unknown"
        if backend not in _FAILED_JOBS_GAUGE_BACKENDS:
            backend = "unknown"
        FAILED_JOBS_CURRENT.labels(
            storage_backend=backend,
            retry_exhausted="true" if retry_exhausted else "false",
        ).set(int(count))


def refresh_stuck_jobs_gauge(stuck_jobs: list) -> None:
    """Set stuck_jobs_current from a discovered stuck-job snapshot."""
    for status in _STUCK_JOB_STATUSES:
        for reason in _STUCK_JOB_REASONS:
            STUCK_JOBS_CURRENT.labels(status=status, stuck_reason=reason).set(0)

    counts: dict[tuple[str, str], int] = {}
    for stuck_job in stuck_jobs:
        status = getattr(stuck_job, "status", "")
        if hasattr(status, "value"):
            status = status.value
        reason = getattr(stuck_job, "stuck_reason", "unknown")
        key = (str(status), str(reason))
        counts[key] = counts.get(key, 0) + 1

    for (status, reason), count in counts.items():
        STUCK_JOBS_CURRENT.labels(status=status, stuck_reason=reason).set(count)


def clear_queue_gauges(queue_name: str) -> None:
    """Zero queue gauges when Redis is unreachable."""
    update_queue_gauges(
        queue_name=queue_name,
        queued=0,
        workers=0,
        started=0,
        finished=0,
        failed=0,
    )
