# Distributed Video Processing Infrastructure

## API Boundary

Public endpoints do not require the admin key:

- `POST /api/v1/videos/upload`
- `GET /api/v1/videos/{id}/status`
- `GET /api/v1/videos/{id}/assets`
- `/health`
- `/api/v1/queue/health`
- `/api/v1/storage/health`

Admin/operator endpoints are under `/api/v1/jobs/*` and require `X-Admin-API-Key`:

```bash
curl -H "X-Admin-API-Key: dev-admin-key" http://localhost:8000/api/v1/jobs/failed
```
