"""Prometheus metrics for API, queue, storage, and worker instrumentation."""

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

VIDEO_PROCESSING_FAILURES_TOTAL = Counter(
    "video_processing_failures_total",
    "Video processing failures",
    ["storage_backend", "error_type"],
)

MANUAL_RETRIES_TOTAL = Counter(
    "manual_retries_total",
    "Manual retries triggered via API",
    ["storage_backend"],
)

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
