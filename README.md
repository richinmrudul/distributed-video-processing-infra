# Distributed Video Processing Infrastructure

g

## Stuck job recovery

`GET /api/v1/jobs/stuck` lists stale `PROCESSING`/`QUEUED` jobs. `POST /api/v1/jobs/recover-stuck` requeues jobs with attempts remaining or fails retry-exhausted jobs, protecting against worker crashes leaving jobs stuck forever.

## Upload idempotency

Uploads support an optional `Idempotency-Key` header. When enabled, a repeated upload with the same key returns the existing `VideoJob` instead of creating duplicate storage, database, or queue work. New uploads return `201 Created`; idempotency hits return `200 OK`. Raw idempotency keys are not logged.

## Reconciler service

The `reconciler` service periodically runs stuck job recovery every `60` seconds by default. Manual stuck-job endpoints still exist. Local Compose runs one reconciler instance; production needs leader election or a distributed lock before scaling it.

The reconciler uses a Redis lock so only one instance performs recovery at a time. Local Compose still runs one reconciler by default; scaling is safer now but still not intended without deeper production leader-election design.
