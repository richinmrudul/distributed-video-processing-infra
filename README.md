# Distributed Video Processing Infrastructure

## Frontend Demo Console

The Next.js demo console is checked by GitHub Actions in the `Frontend Build` workflow. Docker Compose exposes it at `http://localhost:3001`; local `npm run dev` may use another port, such as `3002`, if `3000` is already occupied, so that origin must be present in `CORS_ALLOWED_ORIGINS`.

## Benchmarking

Local benchmark commands, overload scenarios, and worker scaling comparison reports are documented in `docs/benchmarking.md`.
