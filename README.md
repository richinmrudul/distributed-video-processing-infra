# Distributed Video Processing Infrastructure

## Phase 2B — Queue-hardened async processing

Phase **2A** split the API from FFmpeg using **Redis + RQ**. Phase **2B** hardens that path for more production-like behavior:

- **RQ `Retry`** with staggered backoff (`10s`, `30s`, `60s`) aligned to **`VideoJob.max_attempts`**
- **Job execution timeout** (`rq_job_timeout_seconds`, default **600** / 10 minutes) so runaway FFmpeg does not hold workers forever
- **`VideoJob` queue metadata**: `queue_job_id`, `attempt_count`, `max_attempts` (exposed on upload + status responses)
- **Worker idempotency**: skip missing jobs, **never reprocess `COMPLETED`**, cap retries when **`FAILED`** and **`attempt_count >= max_attempts`**, clear `error_message` when retrying
- **Enqueue failure handling**: DB row marked **`FAILED`** with `enqueue_failed:…`; API returns **503** with `video_id` for correlation
- **`GET /api/v1/queue/health`**: Redis connectivity + basic RQ registry sizes (queued / failed / started / deferred)

Phase **2C** (next) can add durable observability (metrics/tracing), DLQ patterns, horizontal scaling, object storage, and migrations (e.g. Alembic) — intentionally out of scope here.

---

## Prerequisites

- **Docker Compose** (recommended): **PostgreSQL**, **Redis**, **API**, **worker**
- **Local-only**: Python 3.12+, PostgreSQL, **Redis**, **ffmpeg**, and two processes (API + `rq worker`) with **`PYTHONPATH=backend:.`**

## Schema changes and local DB

Models use **`create_all`** only (no Alembic yet). After pulling Phase **2B**, if Postgres already has an older `video_jobs` table, **`create_all` will not add new columns**.

For local development, reset the volume:

```bash
docker compose down -v
docker compose up --build
```

---

## Run with Docker Compose

From the repository root:

```bash
docker compose up --build
```

The **worker** runs:

```yaml
command: >
  sh -c "rq worker $$QUEUE_NAME --url $$REDIS_URL"
```

`$$` is escaped so **Compose does not interpolate host variables**; **`$QUEUE_NAME`** and **`$REDIS_URL`** expand **inside the container** from the service `environment`.

Both **api** and **worker** receive:

| Variable | Value (in Compose) |
|----------|---------------------|
| `DATABASE_URL` | `postgresql+psycopg2://video:video@db:5432/video` |
| `REDIS_URL` | `redis://redis:6379/0` |
| `QUEUE_NAME` | `video-processing` |
| `STORAGE_ROOT` | `/data/storage` |

Endpoints:

- **API**: `http://localhost:8000`
- **PostgreSQL**: `localhost:5432` (`video` / `video` / `video`)
- **Redis**: `localhost:6379`
- **Storage**: `./storage` on the host

### Worker logs

```bash
docker compose logs -f worker
```

You should see RQ lines such as **`Listening on video-processing`** plus structured logs (`worker_job_picked_up`, `worker_processing_started`, etc.).

### Queue health

```bash
curl -sS http://localhost:8000/api/v1/queue/health | jq .
```

Expect **`redis_connected": true`**, **`queue_name": "video-processing"**, and registry counts (values depend on workload).

---

## Run locally (API + worker on the host)

1. Start dependencies:

   ```bash
   docker compose up db redis
   ```

2. Install **ffmpeg** (e.g. `brew install ffmpeg`).

3. From the **repository root**:

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

5. **Terminal B — worker** (same env; variables expand in your shell)

   ```bash
   rq worker "$QUEUE_NAME" --url "$REDIS_URL"
   ```

---

## Environment variables

| Variable | Default (in code) | Description |
|----------|-------------------|-------------|
| `DATABASE_URL` | `postgresql+psycopg2://video:video@localhost:5432/video` | SQLAlchemy URL |
| `REDIS_URL` | `redis://redis:6379/0` | Redis for RQ |
| `QUEUE_NAME` | `video-processing` | RQ queue name (API + worker must match) |
| `STORAGE_ROOT` | `storage` | Root for `raw/`, `processed/`, `thumbnails/` |
| `RQ_JOB_TIMEOUT_SECONDS` | `600` | RQ job timeout (FFmpeg) in seconds |
| `LOG_LEVEL` | `INFO` | Logging level |
| `LOG_JSON` | `false` | JSON logs when `true` |

---

## API quick reference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness |
| GET | `/api/v1/queue/health` | Redis + RQ queue/registry snapshot |
| POST | `/api/v1/videos/upload` | Multipart upload; enqueues RQ job (does not wait for FFmpeg) |
| GET | `/api/v1/videos/{video_id}/status` | Job status, paths, queue metadata |

OpenAPI: `http://localhost:8000/docs`

---

## Job lifecycle

`UPLOADED` → `QUEUED` → `PROCESSING` → `COMPLETED` **or** `FAILED`

- **`queue_job_id`**: RQ job id after successful enqueue (null if enqueue failed before assignment)
- **`attempt_count`**: incremented at the **start** of each worker execution (including RQ retries)
- **`max_attempts`**: cap for DB-level “give up” behavior (default **3**); RQ **`Retry(max=max_attempts-1)`** with intervals **`[10, 30, 60]`** seconds

---

## Verification commands

```bash
docker compose down -v
docker compose up --build
```

```bash
curl -sS http://localhost:8000/health
curl -sS http://localhost:8000/api/v1/queue/health | jq .
```

Upload:

```bash
curl -sS -X POST http://localhost:8000/api/v1/videos/upload \
  -F "file=@/path/to/sample.mp4" | jq .
```

Poll (replace `VIDEO_ID`):

```bash
curl -sS "http://localhost:8000/api/v1/videos/VIDEO_ID/status" | jq .
```

### Expected (happy path)

1. Compose brings up **db**, **redis**, **api**, **worker**.
2. **`GET /health`** → `{"status":"ok"}`.
3. Upload returns quickly with **`QUEUED`**, **`queue_job_id` not null**, **`attempt_count` still 0** in the upload response (worker increments on pickup).
4. **`GET .../status`**: after the worker runs, **`attempt_count` is at least 1**, status **`PROCESSING`** then **`COMPLETED`**, paths populated.
5. **`GET /api/v1/queue/health`**: **`redis_connected": true`**.
6. **`storage/processed`** has the **mp4**; **`storage/thumbnails`** has the **jpg**.

If **Redis** is down at upload time, the API responds **503** with a JSON **`detail`** including **`video_id`**; the row is **`FAILED`** with **`enqueue_failed:`** in **`error_message`**.

---

## Troubleshooting

### `TypeError: process_video_job() got an unexpected keyword argument 'timeout'`

If worker logs show **`unexpected keyword argument 'timeout'`**, enqueue options were passed as **worker function keyword arguments** instead of **RQ job options**.

In RQ 2.x, `Queue.enqueue()` / `parse_args` strips **`job_timeout=...`** for the job’s execution limit. A bare **`timeout=...`** is **not** treated as an RQ option and is forwarded to **`process_video_job`**, which only accepts **`job_id`**.

**Fix:** use **`job_timeout=...`** in **`enqueue_video_processing`** (see `backend/app/services/queue_service.py`). Correct worker log lines look like **`workers.video_worker.process_video_job('VIDEO_ID')`**, not **`...('VIDEO_ID', timeout=600)`**.

---

## Architecture (summary)

- **API**: `VideoService` → **`StorageService`** + **`QueueService`** (RQ `Retry`, **`job_timeout`**).
- **Worker**: `workers/video_worker.py` → own DB session → **`ProcessingService`**.
- **Docker**: single image (`backend/Dockerfile`), build context **repo root**, **`PYTHONPATH=/app`**, **`workers/`** + **`app/`** on the image.

---

## Reliability (what Phase 2B improves)

| Problem | Mitigation |
|---------|------------|
| Transient Redis / broker blips | RQ **retry** with backoff |
| Stuck / hung FFmpeg | **Worker job timeout** |
| No correlation to queue | Persist **`queue_job_id`** |
| Opaque retry / give-up | **`attempt_count` / `max_attempts`** in API + DB |
| Blind operations | **`/api/v1/queue/health`** for quick inspection |

---

## Phase 2C (suggested next)

- **Alembic** (or managed migrations) instead of **`create_all`**
- **Metrics and tracing** (Prometheus/OpenTelemetry) without running full k8s
- **Object storage** for raw/processed artifacts
- **DLQ / explicit retry policies**, **worker autoscaling**, **multi-queue** priorities
