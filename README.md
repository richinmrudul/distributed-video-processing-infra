# Distributed Video Processing Infrastructure

## Benchmarking

Run a small local upload benchmark:

```bash
docker compose up --build --scale worker=3
./scripts/run_benchmark.sh
```

Or call the Python runner directly:

```bash
python scripts/benchmark_uploads.py --video-path /path/to/test.mp4 --uploads 20 --concurrency 5
```

View runtime behavior in Grafana at `http://localhost:3000`, Prometheus at `http://localhost:9090`, and Jaeger at `http://localhost:16686`.

The benchmark may hit rate limits or admission control, and results depend on your local machine. Treat it as a local pressure test, not a formal production benchmark.
