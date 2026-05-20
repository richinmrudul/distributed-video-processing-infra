# Operations

Administrative job operations are protected by `X-Admin-API-Key`. Docker Compose uses the dev-only key `dev-admin-key`.

## Failed Jobs

List failed jobs:

```bash
curl -H "X-Admin-API-Key: dev-admin-key" \
  "http://localhost:8000/api/v1/jobs/failed"
```

Retry a failed job:

```bash
curl -X POST -H "X-Admin-API-Key: dev-admin-key" \
  "http://localhost:8000/api/v1/jobs/<video_id>/retry"
```

## Stuck Job Recovery

Inspect stuck jobs:

```bash
curl -H "X-Admin-API-Key: dev-admin-key" \
  "http://localhost:8000/api/v1/jobs/stuck"
```

Recover stuck jobs:

```bash
curl -X POST -H "X-Admin-API-Key: dev-admin-key" \
  "http://localhost:8000/api/v1/jobs/recover-stuck"
```

## Lifecycle Cleanup

Cleanup removes old object-storage assets for completed jobs and retry-exhausted failed jobs. It is idempotent and dry-run oriented. By default, cleanup does not delete database rows; it marks jobs with `cleaned_up_at` and clears object references after object deletion succeeds.

Inspect candidates first:

```bash
curl -H "X-Admin-API-Key: dev-admin-key" \
  "http://localhost:8000/api/v1/jobs/cleanup-candidates"
```

Run a dry-run cleanup:

```bash
curl -X POST -H "X-Admin-API-Key: dev-admin-key" \
  "http://localhost:8000/api/v1/jobs/cleanup?dry_run=true"
```

Execute cleanup:

```bash
curl -X POST -H "X-Admin-API-Key: dev-admin-key" \
  "http://localhost:8000/api/v1/jobs/cleanup?dry_run=false"
```

Retention is controlled by `CLEANUP_COMPLETED_AFTER_DAYS`, `CLEANUP_FAILED_AFTER_DAYS`, `CLEANUP_BATCH_SIZE`, and `CLEANUP_DELETE_DB_ROWS`.
