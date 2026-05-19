# Benchmarking

Use the local benchmark to pressure-test upload acceptance, queueing, and worker throughput on your machine.

```bash
./scripts/run_benchmark.sh
```

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
