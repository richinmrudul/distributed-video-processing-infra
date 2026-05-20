# Benchmarking

Use the local benchmark to pressure-test upload acceptance, queueing, and worker throughput on your machine.

```bash
./scripts/run_benchmark.sh
```

Run controlled overload scenarios:

```bash
./scripts/run_overload_benchmark.sh
```

The overload benchmark validates protection behavior:

- baseline uploads should be accepted and complete
- worker outage scales workers to zero and expects `503` / `insufficient_workers`
- rate-limit pressure sends a burst from one synthetic client and expects `429` / `rate_limited` when local defaults allow it
- queue backlog protection can be tested manually by lowering `MAX_QUEUE_DEPTH_FOR_UPLOADS` and running a burst

For a custom video and larger run:

```bash
python scripts/benchmark_uploads.py --video-path /path/to/test.mp4 --uploads 20 --concurrency 5 --json-output benchmark-results/latest.json
python scripts/render_benchmark_report.py --input benchmark-results/latest.json --output benchmark-results/latest.md
```

Key fields to watch:

- `throughput_uploads_per_second`: accepted/rejected upload attempt rate from the client side.
- `p95_upload_latency_seconds`: tail latency for upload requests.
- `p95_processing_duration_seconds`: tail worker processing time for completed/failed jobs.
- `upload_rejection_count`: pressure from rate limiting, admission control, or unavailable dependencies.
- `queued_jobs_count` and `worker_count`: whether work is backing up behind available workers.

An illustrative small local run might show all uploads accepted, queue depth near zero, and processing duration under a second. That is only a smoke benchmark; larger videos, fewer workers, rate limits, or slower CPUs will change the result.

Generated JSON and Markdown reports are written under `benchmark-results/` and ignored by Git.

## Worker scaling benchmark

Compare local throughput and processing duration across worker replica counts:

```bash
./scripts/run_scaling_benchmark.sh
```

Example with explicit matrix values:

```bash
WORKER_COUNTS="1 3 5" UPLOADS=15 CONCURRENCY=5 ./scripts/run_scaling_benchmark.sh
```

Outputs are written under `benchmark-results/` and ignored by Git:

- `benchmark-results/scaling-workers-1.json`
- `benchmark-results/scaling-workers-3.json`
- `benchmark-results/scaling-workers-5.json`
- `benchmark-results/scaling-comparison.md`

The comparison report highlights throughput, p95 upload latency, processing duration, wall-clock time, queue pressure, and the fastest scenarios. Results are local-machine dependent and should not be presented as production benchmark claims.
