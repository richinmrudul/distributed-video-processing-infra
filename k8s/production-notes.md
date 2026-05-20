# Kubernetes Production Notes

## Purpose

These manifests are Kubernetes readiness manifests, not a complete production platform. They define separate workloads for the API, RQ workers, and automated reconciler so the system can be deployed and scaled along its natural operational boundaries.

## Recommended Production Dependency Mapping

| Local Docker Compose service | Production recommendation |
| --- | --- |
| `postgres` | Managed Postgres such as RDS, Cloud SQL, Neon, Supabase, or another production Postgres service |
| `redis` | Managed Redis such as ElastiCache, Memorystore, Upstash, or another production Redis service |
| `minio` | S3, R2, a GCS S3-compatible layer, or another durable managed object storage service |
| `prometheus` | Prometheus Operator or managed Prometheus |
| `grafana` | Grafana Cloud or managed Grafana |
| `jaeger` | Tempo, Honeycomb, Datadog, Jaeger, or another OTLP-compatible tracing backend |

## Workload Scaling Model

The API Deployment can scale horizontally behind the `video-processing-api` ClusterIP Service. API replicas should be stateless and share Postgres, Redis, and object storage.

The Worker Deployment scales independently based on queue pressure and processing throughput. More worker replicas increase processing capacity, assuming Redis, object storage, CPU, and FFmpeg throughput are not the bottleneck.

The Reconciler Deployment defaults to one replica. The Redis lock protects against duplicate reconciler work, but one replica is still the normal deployment unless you are testing failover behavior.

## Migrations

Docker Compose may run Alembic migrations during API startup. Production Kubernetes should run migrations as a separate Job or release step before rolling out API replicas.

Do not let multiple API pods run migrations concurrently. Keep API startup focused on serving traffic after the schema is already current.

## Secrets

`k8s/secrets.example.yaml` is a template only. Copy it to `k8s/secrets.yaml`, replace every placeholder, and keep the real file out of Git.

Real deployments should use a real secret manager, sealed secrets, or external secrets. Never commit `k8s/secrets.yaml`.

Set `APP_ENV=production` and provide real values for Postgres, Redis, object storage, and `ADMIN_API_KEY`. Production config validation rejects the Docker Compose dev admin key, wildcard CORS, and obvious local development dependency URLs.

Restrict `CORS_ALLOWED_ORIGINS` to the real frontend or operator-console domains. Do not expose `/api/v1/jobs/*` admin endpoints publicly without the API key and normal reverse-proxy protections.

## Observability

Worker and reconciler metrics ports are exposed internally. Prometheus scrape annotations are included on those pods.

If using Prometheus Operator, prefer `ServiceMonitor` or `PodMonitor` resources in a later phase. Traces should point to an OTLP collector or managed tracing backend via `OTEL_EXPORTER_OTLP_ENDPOINT`.

## Storage

Local MinIO is useful for development. Production should use durable object storage.

Raw, processed, and thumbnail buckets should be lifecycle-managed. Consider retention rules for raw uploads, processed outputs, failed-job artifacts, and thumbnails.

## Ingress And TLS

The API Service is `ClusterIP` only. Add Ingress or Gateway API resources and TLS later.

## Autoscaling

HPA can be added later for API CPU, memory, or request-rate signals. Worker autoscaling should ideally use queue depth or custom metrics rather than CPU alone.

Do not add HPA in this phase.
