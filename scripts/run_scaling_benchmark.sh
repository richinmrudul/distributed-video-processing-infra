#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

WORKER_COUNTS="${WORKER_COUNTS:-1 3 5}"
UPLOADS="${UPLOADS:-15}"
CONCURRENCY="${CONCURRENCY:-5}"
BASE_URL="${BASE_URL:-http://localhost:8000}"
BENCHMARK_OUTPUT_DIR="${BENCHMARK_OUTPUT_DIR:-benchmark-results}"
SKIP_COMPOSE_UP="${SKIP_COMPOSE_UP:-0}"
RESTORE_STACK="${RESTORE_STACK:-1}"
COOLDOWN_SECONDS="${COOLDOWN_SECONDS:-5}"

print_diagnostics() {
  (
    set +e
    echo
    echo "Docker Compose status"
    docker compose ps
    echo
    echo "API logs"
    docker compose logs api --tail=80
    echo
    echo "Worker logs"
    docker compose logs worker --tail=80
  )
}

restore_stack() {
  if [[ "$RESTORE_STACK" == "1" ]]; then
    echo
    echo "Restoring worker scale to 3"
    docker compose up -d --scale worker=3 >/dev/null
  fi
}

trap 'echo "Scaling benchmark failed; printing diagnostics."; print_diagnostics; exit 1' ERR
trap restore_stack EXIT

wait_for_api() {
  echo "Waiting for API health at ${BASE_URL}/health"
  for _ in {1..60}; do
    if curl -fsS "${BASE_URL}/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  curl -fsS "${BASE_URL}/health" >/dev/null
}

ensure_video_path() {
  if [[ -n "${TEST_VIDEO_PATH:-}" ]]; then
    return 0
  fi
  if command -v ffmpeg >/dev/null 2>&1; then
    return 0
  fi

  local generated_video="/tmp/distributed-video-processing-scaling-benchmark.mp4"
  if [[ ! -f "$generated_video" ]]; then
    docker compose exec -T api ffmpeg \
      -y \
      -f lavfi \
      -i color=c=blue:s=160x120:d=1 \
      -pix_fmt yuv420p \
      -movflags +faststart \
      /tmp/scaling_benchmark_test.mp4 >/dev/null 2>&1
    docker compose cp api:/tmp/scaling_benchmark_test.mp4 "$generated_video" >/dev/null
  fi
  export TEST_VIDEO_PATH="$generated_video"
}

python_bin() {
  if [[ "${PYTHON_BIN:-python}" == "python" && -x ".venv/bin/python" ]]; then
    echo ".venv/bin/python"
  else
    echo "${PYTHON_BIN:-python}"
  fi
}

check_rate_limit_guidance() {
  local json_path="$1"
  "$PYTHON" - "$json_path" <<'PY'
import json
import sys

summary = json.loads(open(sys.argv[1], encoding="utf-8").read()).get("summary", {})
reason_counts = summary.get("rejection_reason_counts", {})
rate_limited = int(reason_counts.get("rate_limited", 0))
if rate_limited:
    print()
    print(
        "NOTE: rate limiting affected this scenario. For scaling-only experiments, "
        "increase UPLOAD_RATE_LIMIT_MAX_REQUESTS or lower UPLOADS/CONCURRENCY."
    )
PY
}

if [[ "$SKIP_COMPOSE_UP" != "1" ]]; then
  docker compose up --build --scale worker=3 -d
fi

wait_for_api
ensure_video_path

PYTHON="$(python_bin)"
mkdir -p "$BENCHMARK_OUTPUT_DIR"

inputs=()
for worker_count in $WORKER_COUNTS; do
  echo
  echo "Running worker scaling scenario: workers=${worker_count}, uploads=${UPLOADS}, concurrency=${CONCURRENCY}"
  docker compose up -d --scale "worker=${worker_count}" >/dev/null
  sleep "$COOLDOWN_SECONDS"
  wait_for_api

  json_path="${BENCHMARK_OUTPUT_DIR}/scaling-workers-${worker_count}.json"
  md_path="${BENCHMARK_OUTPUT_DIR}/scaling-workers-${worker_count}.md"
  client_id="10.240.$((worker_count % 200 + 1)).13"
  args=(
    scripts/benchmark_uploads.py
    --base-url "$BASE_URL"
    --uploads "$UPLOADS"
    --concurrency "$CONCURRENCY"
    --client-id "$client_id"
    --json-output "$json_path"
  )
  if [[ -n "${TEST_VIDEO_PATH:-}" ]]; then
    args+=(--video-path "$TEST_VIDEO_PATH")
  fi

  "$PYTHON" "${args[@]}"
  "$PYTHON" scripts/render_benchmark_report.py --input "$json_path" --output "$md_path" >/dev/null
  echo "Scenario report: $md_path"
  check_rate_limit_guidance "$json_path"
  inputs+=("$json_path")

  if [[ "$COOLDOWN_SECONDS" != "0" ]]; then
    echo "Cooling down for ${COOLDOWN_SECONDS}s"
    sleep "$COOLDOWN_SECONDS"
  fi
done

"$PYTHON" scripts/render_scaling_report.py \
  --inputs "${inputs[@]}" \
  --output-md "${BENCHMARK_OUTPUT_DIR}/scaling-comparison.md" \
  --output-json "${BENCHMARK_OUTPUT_DIR}/scaling-comparison.json"

echo
echo "Scaling comparison report: ${BENCHMARK_OUTPUT_DIR}/scaling-comparison.md"
echo
echo "Dashboards:"
echo "  Grafana:    http://localhost:3000"
echo "  Prometheus: http://localhost:9090"
echo "  Jaeger:     http://localhost:16686"
