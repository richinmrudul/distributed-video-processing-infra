# Distributed Video Processing Infrastructure

## Frontend Demo Console

The lightweight Next.js console at `http://localhost:3001` demonstrates the upload flow, job status timeline, system health checks, admin failed/stuck job operations, and local observability links. It remains a demo console for the infrastructure, not the core product.

Docker Compose exposes the frontend on `http://localhost:3001`. Local `next dev` may choose another port such as `http://localhost:3002` when `3000` is occupied, so that origin must be included in the backend `CORS_ALLOWED_ORIGINS` setting.
