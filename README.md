# Distributed Video Processing Infrastructure

## Failed jobs and manual retry

Simulate a failed job (corrupt upload):

```bash
echo "not a real video" > /tmp/bad.mp4
curl -X POST http://localhost:8000/api/v1/videos/upload -F "file=@/tmp/bad.mp4"
curl http://localhost:8000/api/v1/videos/{id}/status
```

List failed jobs:

```bash
curl http://localhost:8000/api/v1/jobs/failed
curl 'http://localhost:8000/api/v1/jobs/failed?retry_exhausted=true'
```

Manually retry a failed job (reuses existing raw storage; does not re-upload):

```bash
curl -X POST http://localhost:8000/api/v1/jobs/{id}/retry
```

Failure metrics (`failed_jobs_current`, `video_manual_retries_total`) refresh on the API scrape after calling `GET /api/v1/jobs/failed`. Grafana **Distributed Video Processing Overview** includes failure/retry panels.

## Worker metrics

Each worker container serves Prometheus metrics on port **9100** inside the Compose network (`/metrics`). Ports are not published to the host. Prometheus scrapes workers via Docker DNS (`worker` service name). RQ job metrics are aggregated with Prometheus multiprocess mode (`PROMETHEUS_MULTIPROC_DIR`).

## Prometheus alerts

Alert rules live in `infra/prometheus/rules/`. View firing/pending alerts at http://localhost:9090/alerts. Alertmanager is not configured yet (no Slack/PagerDuty routing).

