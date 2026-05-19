# Distributed Video Processing Infrastructure

## Admin Endpoints

Operator endpoints under `/api/v1/jobs/*` require `X-Admin-API-Key`.

```bash
curl -H "X-Admin-API-Key: dev-admin-key" http://localhost:8000/api/v1/jobs/failed
```

Docker Compose uses the dev-only key `dev-admin-key`. Public video endpoints do not require this key. In production, set `ADMIN_API_KEY` to a real secret.


