# Distributed Video Processing Infrastructure

Phase **2A** moves **FFmpeg off the API** and into a **dedicated RQ worker** backed by **Redis**. The API still accepts uploads, writes **raw files** and **PostgreSQL** `VideoJob` rows, then **enqueues** work and returns with status **`QUEUED`**. A separate **worker** process pulls jobs, runs **`ProcessingService`**, and updates the database to **`COMPLETED`** or **`FAILED`**.

## Prerequisites

- **Docker Compose** (recommended): runs **PostgreSQL**, **Redis**, **API**, and **worker**.
- **Local-only**: Python 3.12+, PostgreSQL 16+, **Redis**, **ffmpeg**, and two processes (API + `rq worker`) with correct **`PYTHONPATH`**.

## Run with Docker Compose (recommended)

From the repository root:

```bash
docker compose up --build
```

- **API**: `http://localhost:8000`
- **PostgreSQL**: `localhost:5432` (user `video`, password `video`, database `video`)
- **Redis**: `localhost:6379`
- **Uploads and outputs**: `./storage` on the host (mounted into API and worker)

Processing is **asynchronous**: the upload response returns quickly with **`QUEUED`**; poll **`GET /api/v1/videos/{id}/status`** until **`COMPLETED`** or **`FAILED`**.

### Worker logs

```bash
docker compose logs -f worker
```

You should see structured events such as `worker_job_picked_up`, `worker_processing_started`, and `worker_processing_completed` (or failure logs).

## Run locally (API and worker on the host)

1. Start dependencies (or equivalents):

   ```bash
   docker compose up db redis
   ```

2. Install **ffmpeg** (e.g. `brew install ffmpeg` on macOS).

3. From the **repository root** (so `storage/` and the `workers` package resolve correctly):

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r backend/requirements.txt
   export PYTHONPATH=backend:.
   export DATABASE_URL=postgresql+psycopg2://video:video@localhost:5432/video
   export REDIS_URL=redis://localhost:6379/0
   export QUEUE_NAME=video-processing
   export STORAGE_ROOT=storage
   ```

4. **Terminal A — API**

   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

5. **Terminal B — worker**

   ```bash
   rq worker "$QUEUE_NAME" --url "$REDIS_URL"
   ```

## Environment variables

| Variable | Default (in code) | Description |
|----------|-------------------|-------------|
| `DATABASE_URL` | `postgresql+psycopg2://video:video@localhost:5432/video` | SQLAlchemy URL |
| `REDIS_URL` | `redis://redis:6379/0` | Redis for RQ (use `redis://localhost:6379/0` on the host) |
| `QUEUE_NAME` | `video-processing` | RQ queue name (API enqueue and worker **must** match) |
| `STORAGE_ROOT` | `storage` (relative to process CWD) | Root for `raw/`, `processed/`, `thumbnails/` |
| `LOG_LEVEL` | `INFO` | Logging level |
| `LOG_JSON` | `false` | Set to `true` for JSON logs (structlog) |

## API quick reference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness |
| POST | `/api/v1/videos/upload` | Multipart upload; enqueues processing (**does not** wait for FFmpeg) |
| GET | `/api/v1/videos/{video_id}/status` | Job status and paths |

OpenAPI UI: `http://localhost:8000/docs`

## Job lifecycle (Phase 2A)

`UPLOADED` → `QUEUED` → `PROCESSING` → `COMPLETED` or `FAILED`

If enqueue to Redis fails after the file is stored, the job is marked **`FAILED`** with `error_message` starting with `enqueue_failed:`.

## Test an upload

```bash
curl -sS -X POST "http://localhost:8000/api/v1/videos/upload" \
  -F "file=@/path/to/sample.mp4" | jq .
```

Poll until `status` is terminal:

```bash
curl -sS "http://localhost:8000/api/v1/videos/VIDEO_ID/status" | jq .
```

## Verification checklist (Phase 2A)

Expected behavior:

1. `docker compose up --build` starts **db**, **redis**, **api**, and **worker**.
2. `GET /health` returns `{"status":"ok"}`.
3. Upload returns quickly with **`QUEUED`** (and `processed_path` / `thumbnail_path` still null).
4. **Worker** logs show processing started (and completed for a valid file).
5. `GET .../status` eventually returns **`COMPLETED`** (or **`FAILED`** if FFmpeg/input fails).
6. `storage/processed` contains the output **mp4**.
7. `storage/thumbnails` contains the **jpg** thumbnail.

## Architecture

- **API**: `VideoService` uses **`StorageService`** and **`QueueService`** (RQ by import path `workers.video_worker.process_video_job`).
- **Worker**: `workers/video_worker.py` opens its own DB session and calls **`ProcessingService`** (same FFmpeg logic as Phase 1).
- **Docker**: one **backend** image (`backend/Dockerfile`); build context is the **repo root** so the image includes both `app/` and `workers/`. **`PYTHONPATH=/app`**.

## Phase 2B (next bottlenecks)

Phase 2A still uses **one default RQ queue**, **no automatic retries**, **no DLQ**, and **no autoscaling** of workers. Redis and worker processes are **single-instance** in Compose; **horizontal scaling**, **observability**, **backpressure**, and **failure isolation** remain for later phases.
