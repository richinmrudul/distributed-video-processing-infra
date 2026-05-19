# Kubernetes Environment Reference

This reference lists the important environment variables used by the application. Values marked `Secret` should come from `video-processing-secrets` or a real secret manager. Values marked `Config` can live in `video-processing-config` or workload-specific env blocks.

## Database

| Env var | Controls | Type | Safe dev example |
| --- | --- | --- | --- |
| `DATABASE_URL` | SQLAlchemy Postgres connection URL | Secret | `postgresql+psycopg2://video:video@db:5432/video` |

## Redis / Queue

| Env var | Controls | Type | Safe dev example |
| --- | --- | --- | --- |
| `REDIS_URL` | Redis connection URL for RQ, rate limiting, and reconciler lock | Secret | `redis://redis:6379/0` |
| `QUEUE_NAME` | RQ queue name | Config | `video-processing` |
| `RQ_JOB_TIMEOUT_SECONDS` | RQ job timeout | Config | `600` |

## Object Storage

| Env var | Controls | Type | Safe dev example |
| --- | --- | --- | --- |
| `STORAGE_BACKEND` | Storage backend mode, `local` or `object` | Config | `object` |
| `OBJECT_STORAGE_ENDPOINT` | Internal S3-compatible endpoint | Secret | `http://minio:9000` |
| `OBJECT_STORAGE_PUBLIC_ENDPOINT` | Public endpoint used for presigned URLs | Secret | `http://localhost:9000` |
| `OBJECT_STORAGE_ACCESS_KEY` | S3-compatible access key | Secret | `minioadmin` |
| `OBJECT_STORAGE_SECRET_KEY` | S3-compatible secret key | Secret | `minioadmin` |
| `OBJECT_STORAGE_REGION` | Object storage region | Secret | `us-east-1` |
| `OBJECT_STORAGE_SECURE` | Whether the object storage client uses TLS | Secret | `false` |
| `RAW_VIDEO_BUCKET` | Bucket for raw uploads | Config | `raw-videos` |
| `PROCESSED_VIDEO_BUCKET` | Bucket for processed videos | Config | `processed-videos` |
| `THUMBNAIL_BUCKET` | Bucket for thumbnails | Config | `thumbnails` |
| `PRESIGNED_URL_EXPIRES_SECONDS` | Presigned asset URL TTL | Config | `3600` |
| `STORAGE_ROOT` | Local filesystem storage root when `STORAGE_BACKEND=local` | Config | `/data/storage` |

## Upload Protection

| Env var | Controls | Type | Safe dev example |
| --- | --- | --- | --- |
| `UPLOAD_ADMISSION_CONTROL_ENABLED` | Enables queue/worker admission checks before upload work | Config | `true` |
| `MAX_QUEUE_DEPTH_FOR_UPLOADS` | Queue depth threshold for upload admission rejection | Config | `50` |
| `MIN_AVAILABLE_WORKERS_FOR_UPLOADS` | Minimum workers required to accept new upload work | Config | `1` |
| `UPLOAD_RATE_LIMIT_ENABLED` | Enables Redis-backed upload rate limiting | Config | `true` |
| `UPLOAD_RATE_LIMIT_MAX_REQUESTS` | Upload request limit per window | Config | `10` |
| `UPLOAD_RATE_LIMIT_WINDOW_SECONDS` | Rate-limit window duration | Config | `60` |
| `UPLOAD_VALIDATION_ENABLED` | Enables upload validation | Config | `true` |
| `MAX_UPLOAD_BYTES` | Maximum request/upload size | Config | `104857600` |
| `ALLOWED_VIDEO_EXTENSIONS` | Allowed upload filename extensions | Config | `.mp4,.mov,.mkv,.webm` |
| `ALLOWED_VIDEO_CONTENT_TYPES` | Allowed upload content types | Config | `video/mp4,video/quicktime,video/x-matroska,video/webm,application/octet-stream` |

## Idempotency

| Env var | Controls | Type | Safe dev example |
| --- | --- | --- | --- |
| `UPLOAD_IDEMPOTENCY_ENABLED` | Enables optional `Idempotency-Key` upload behavior | Config | `true` |
| `IDEMPOTENCY_KEY_MAX_LENGTH` | Maximum accepted idempotency key length | Config | `128` |

## Admin Auth

| Env var | Controls | Type | Safe dev example |
| --- | --- | --- | --- |
| `ADMIN_AUTH_ENABLED` | Enables admin API key protection for `/api/v1/jobs/*` | Config | `true` |
| `ADMIN_API_KEY` | Admin API key expected in `X-Admin-API-Key` | Secret | `dev-admin-key` |

## Worker / Reconciler Metrics

| Env var | Controls | Type | Safe dev example |
| --- | --- | --- | --- |
| `WORKER_METRICS_PORT` | Worker Prometheus metrics port | Config | `9100` |
| `RECONCILER_METRICS_PORT` | Reconciler Prometheus metrics port | Config | `9200` |

## Reconciler

| Env var | Controls | Type | Safe dev example |
| --- | --- | --- | --- |
| `STUCK_PROCESSING_TIMEOUT_SECONDS` | Age threshold for stuck `PROCESSING` jobs | Config | `300` |
| `STUCK_QUEUED_TIMEOUT_SECONDS` | Age threshold for stuck `QUEUED` jobs | Config | `300` |
| `STUCK_JOB_RECOVERY_ENABLED` | Enables stuck-job recovery behavior | Config | `true` |
| `RECONCILER_ENABLED` | Enables reconciler loop | Config | `true` |
| `RECONCILER_INTERVAL_SECONDS` | Delay between reconciler runs | Config | `60` |
| `RECONCILER_STARTUP_DELAY_SECONDS` | Initial reconciler startup delay | Config | `10` |
| `RECONCILER_ONESHOT` | Runs reconciler once and exits when true | Config | `false` |
| `RECONCILER_LOCK_ENABLED` | Enables Redis distributed lock around reconciler work | Config | `true` |
| `RECONCILER_LOCK_KEY` | Redis key used for reconciler lock | Config | `reconciler:stuck-job-recovery` |
| `RECONCILER_LOCK_TTL_SECONDS` | Reconciler lock TTL | Config | `55` |
| `RECONCILER_LOCK_ACQUIRE_TIMEOUT_SECONDS` | Lock acquisition timeout | Config | `2` |

## OpenTelemetry

| Env var | Controls | Type | Safe dev example |
| --- | --- | --- | --- |
| `TRACING_ENABLED` | Enables OpenTelemetry tracing setup | Config | `true` |
| `OTEL_SERVICE_NAME` | Workload-specific service name for traces | Config | `video-processing-api` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP collector endpoint | Config | `http://jaeger:4317` |

## Logging

| Env var | Controls | Type | Safe dev example |
| --- | --- | --- | --- |
| `LOG_LEVEL` | Application log level | Config | `INFO` |
| `LOG_JSON` | JSON log rendering | Config | `true` |
