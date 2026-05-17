# Distributed Video Processing Infrastructure

g

## Stuck job recovery

`GET /api/v1/jobs/stuck` lists stale `PROCESSING`/`QUEUED` jobs. `POST /api/v1/jobs/recover-stuck` requeues jobs with attempts remaining or fails retry-exhausted jobs, protecting against worker crashes leaving jobs stuck forever.