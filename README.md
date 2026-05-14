# Distributed Video Processing Infrastructure

- **Compose default:** `STORAGE_BACKEND=object` (MinIO). Use `STORAGE_BACKEND=local` for the previous on-disk pipeline only.
- **MinIO console:** http://localhost:9001 — **minioadmin** / **minioadmin**
- **Check object storage:** `curl -sS http://localhost:8000/api/v1/storage/health | jq .` — then upload via `POST /api/v1/videos/upload` and poll `GET /api/v1/videos/{id}/status` (`storage_backend`, `raw_object_key`, `processed_object_key`, `s3://…` paths when complete).
