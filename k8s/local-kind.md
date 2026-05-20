# Local kind Smoke Test

This is a local Kubernetes smoke test for the readiness manifests. It is not a production deployment path.

Docker Compose remains the primary local development workflow. Production Kubernetes should use managed Postgres, managed Redis, and durable S3-compatible object storage.

## Requirements

- Docker
- kubectl
- kind

Install references:

```bash
# macOS examples
brew install kind kubectl
```

See the upstream docs for other platforms:

- kind: https://kind.sigs.k8s.io/docs/user/quick-start/
- kubectl: https://kubernetes.io/docs/tasks/tools/

## What It Validates

The smoke test validates that local Kubernetes can start:

- dev-only Postgres
- dev-only Redis
- dev-only MinIO
- MinIO bucket bootstrap Job
- API Deployment
- worker Deployment
- reconciler Deployment
- frontend Deployment

It then port-forwards the API to `http://localhost:18000`, the frontend to `http://localhost:13001`, and checks:

- `GET /health`
- `GET /api/v1/queue/health` with Redis connected

## Run

From the repository root:

```bash
./scripts/kind_smoke_test.sh
```

Optional upload smoke:

```bash
RUN_KIND_UPLOAD_SMOKE=1 ./scripts/kind_smoke_test.sh
```

The optional upload smoke requires local `ffmpeg`. It uploads a tiny generated MP4 and polls until the job reaches `COMPLETED` or `FAILED`.

## Overlay

The local overlay lives in:

```text
k8s/overlays/kind/
```

It uses local `:kind` images, `APP_ENV=development`, dev-only credentials, and CORS origins for `http://localhost:13001` and `http://127.0.0.1:13001`.

Do not use the kind overlay for production.

## Registry Images

The kind smoke test intentionally builds local images and loads them into kind:

- `distributed-video-processing-infra-api:kind`
- `distributed-video-processing-infra-worker:kind`
- `distributed-video-processing-infra-reconciler:kind`
- `distributed-video-processing-infra-frontend:kind`

Cloud Kubernetes deployments should use the GHCR images published by GitHub Actions instead:

- `ghcr.io/richinmrudul/distributed-video-processing-infra-api:latest`
- `ghcr.io/richinmrudul/distributed-video-processing-infra-worker:latest`
- `ghcr.io/richinmrudul/distributed-video-processing-infra-reconciler:latest`
- `ghcr.io/richinmrudul/distributed-video-processing-infra-frontend:latest`

If GHCR packages are private, configure Kubernetes `imagePullSecrets` or make the packages public before deploying.
