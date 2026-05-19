#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BASE_URL="${BASE_URL:-http://localhost:8000}"
UPLOADS="${UPLOADS:-10}"
CONCURRENCY="${CONCURRENCY:-3}"

if [[ "${SKIP_COMPOSE_UP:-0}" != "1" ]]; then
  docker compose up --build --scale worker=3 -d
fi

echo "Waiting for API health at ${BASE_URL}/health"
for _ in {1..60}; do
  if curl -fsS "${BASE_URL}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
curl -fsS "${BASE_URL}/health" >/dev/null

if [[ -z "${TEST_VIDEO_PATH:-}" ]] && ! command -v ffmpeg >/dev/null 2>&1; then
  GENERATED_VIDEO="/tmp/distributed-video-processing-benchmark.mp4"
  if [[ ! -f "$GENERATED_VIDEO" ]]; then
    docker compose exec -T api ffmpeg \
      -y \
      -f lavfi \
      -i color=c=blue:s=160x120:d=1 \
      -pix_fmt yuv420p \
      -movflags +faststart \
      /tmp/benchmark_test.mp4 >/dev/null 2>&1
    docker compose cp api:/tmp/benchmark_test.mp4 "$GENERATED_VIDEO" >/dev/null
  fi
  export TEST_VIDEO_PATH="$GENERATED_VIDEO"
fi

PYTHON_BIN="${PYTHON_BIN:-python}"
if [[ "${PYTHON_BIN}" == "python" && -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi

args=(
  scripts/benchmark_uploads.py
  --base-url "$BASE_URL"
  --uploads "$UPLOADS"
  --concurrency "$CONCURRENCY"
)

if [[ -n "${TEST_VIDEO_PATH:-}" ]]; then
  args+=(--video-path "$TEST_VIDEO_PATH")
fi

"$PYTHON_BIN" "${args[@]}"

echo
echo "Dashboards:"
echo "  Grafana:    http://localhost:3000"
echo "  Prometheus: http://localhost:9090"
echo "  Jaeger:     http://localhost:16686"
