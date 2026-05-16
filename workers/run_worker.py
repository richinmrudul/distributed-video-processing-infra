"""RQ worker entrypoint: logging, Prometheus /metrics on :9100, then RQ worker loop.

RQ 2.x runs each job in a separate work-horse process. Prometheus multiprocess mode
aggregates metrics from those children into the HTTP server in this parent process.
"""

import glob
import os
import socket

from prometheus_client import CollectorRegistry, multiprocess, start_http_server
from redis import Redis
from rq import Worker

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.tracing import configure_tracing

configure_logging(log_level=settings.log_level, log_json=settings.log_json)
log = get_logger(__name__)


def _prepare_multiprocess_dir() -> None:
    multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if not multiproc_dir:
        return
    os.makedirs(multiproc_dir, exist_ok=True)
    for path in glob.glob(os.path.join(multiproc_dir, "*")):
        try:
            os.remove(path)
        except OSError:
            pass


def main() -> None:
    configure_tracing(settings.otel_service_name)
    _prepare_multiprocess_dir()

    port = settings.worker_metrics_port
    registry = CollectorRegistry()
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        multiprocess.MultiProcessCollector(registry)
    start_http_server(port, addr="0.0.0.0", registry=registry)
    log.info(
        "worker_metrics_server_started",
        port=port,
        hostname=socket.gethostname(),
        metrics_path="/metrics",
        multiproc=bool(os.environ.get("PROMETHEUS_MULTIPROC_DIR")),
    )

    conn = Redis.from_url(settings.redis_url, decode_responses=False)
    worker = Worker([settings.queue_name], connection=conn)
    log.info("rq_worker_starting", queue_name=settings.queue_name)
    worker.work()


if __name__ == "__main__":
    main()
