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
