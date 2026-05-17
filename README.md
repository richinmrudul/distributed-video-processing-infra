# Distributed Video Processing Infrastructure

g

## Stuck job recovery

`GET /api/v1/jobs/stuck` lists stale `PROCESSING`/`QUEUED` jobs. `POST /api/v1/jobs/recover-stuck` requeues jobs with attempts remaining or fails retry-exhausted jobs, protecting against worker crashes leaving jobs stuck forever.

## Reconciler service

The `reconciler` service periodically runs stuck job recovery every `60` seconds by default. Manual stuck-job endpoints still exist. Local Compose runs one reconciler instance; production needs leader election or a distributed lock before scaling it.