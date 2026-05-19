# Distributed Video Processing Infrastructure

## Benchmarking

Run a local upload benchmark:

```bash
./scripts/run_benchmark.sh
```

Generated JSON and Markdown reports are written to `benchmark-results/`, with `latest.md` as the easiest local report to review. Generated benchmark files are ignored by Git.

Controlled overload scenarios are available locally:

```bash
./scripts/run_overload_benchmark.sh
```

## Kubernetes

Kubernetes readiness manifests live in `k8s/`. Docker Compose remains the local development path. The Kubernetes manifests assume external Postgres, Redis, and object storage; see `k8s/README.md`.
