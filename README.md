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

