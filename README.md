# Distributed Video Processing Infrastructure

Phase 1 delivers a **local FastAPI API** that accepts video uploads, records job metadata in **PostgreSQL**, stores raw files under `storage/raw`, and runs **FFmpeg** transcoding plus a thumbnail pass into `storage/processed` and `storage/thumbnails`. Processing is **synchronous in the HTTP request** for now, but the **service layer** is split so work can move to background workers later.

## Prerequisites

- Docker and Docker Compose (for PostgreSQL and the API container), **or** Python 3.12 or newer, PostgreSQL 16+, and **ffmpeg** on your PATH for a fully local run.

## Run with Docker Compose (recommended)

From the repository root:

```bash
docker compose up --build
```

- API: `http://localhost:8000`
- PostgreSQL: `localhost:5432` (user `video`, password `video`, database `video`)
- Uploads and outputs are persisted under `./storage` on the host.

## Run the API locally (without the API container)

1. Start only the database (or use your own PostgreSQL and set `DATABASE_URL`):

   ```bash
   docker compose up db
   ```

2. Install dependencies and **ffmpeg** (e.g. `brew install ffmpeg` on macOS).

3. From the **repository root** (so `storage/` resolves correctly):

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r backend/requirements.txt
   export PYTHONPATH=backend
   export DATABASE_URL=postgresql+psycopg2://video:video@localhost:5432/video
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

Optional environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+psycopg2://video:video@localhost:5432/video` | SQLAlchemy URL |
| `STORAGE_ROOT` | `storage` (relative to current working directory) | Root for `raw/`, `processed/`, `thumbnails/` |
| `LOG_LEVEL` | `INFO` | Logging level |
| `LOG_JSON` | `false` | Set to `true` for JSON logs (structlog) |

## API quick reference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness |
| POST | `/api/v1/videos/upload` | Multipart upload; runs FFmpeg in-request |
| GET | `/api/v1/videos/{video_id}/status` | Job status and paths |

Interactive docs: `http://localhost:8000/docs`

## Test an upload

```bash
curl -sS -X POST "http://localhost:8000/api/v1/videos/upload" \
  -F "file=@/path/to/sample.mp4" | jq .
```

Then poll status (replace `VIDEO_ID` with the `id` from the response):

```bash
curl -sS "http://localhost:8000/api/v1/videos/VIDEO_ID/status" | jq .
```

## What success looks like

- `GET /health` returns `{"status":"ok"}`.
- Upload returns **201** with `id`, `status`, `original_filename`, and `raw_path`. After processing finishes in the same request, `status` is **`COMPLETED`** (or **`FAILED`** if FFmpeg is missing or the file is invalid).
- `GET .../status` shows `processed_path` and `thumbnail_path` when completed.
- On disk you see a new file under `storage/raw`, an MP4 under `storage/processed`, and a JPEG under `storage/thumbnails`.

## Architecture (Phase 1)

Routes delegate to **`VideoService`**, which uses **`StorageService`** (files) and **`ProcessingService`** (FFmpeg). Phase 2 can enqueue work instead of calling `_run_processing` inside the request without rewriting the storage or FFmpeg modules.
