#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BASE_URL="${BASE_URL:-http://localhost:8000}"
ADMIN_API_KEY="${ADMIN_API_KEY:-dev-admin-key}"
BENCHMARK_OUTPUT_DIR="${BENCHMARK_OUTPUT_DIR:-benchmark-results}"
SKIP_COMPOSE_UP="${SKIP_COMPOSE_UP:-0}"
RESTORE_STACK="${RESTORE_STACK:-1}"

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

trap 'echo "Overload benchmark failed; printing diagnostics."; print_diagnostics; exit 1' ERR
trap restore_stack EXIT

if [[ "$SKIP_COMPOSE_UP" != "1" ]]; then
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
  GENERATED_VIDEO="/tmp/distributed-video-processing-overload-benchmark.mp4"
  if [[ ! -f "$GENERATED_VIDEO" ]]; then
    docker compose exec -T api ffmpeg \
      -y \
      -f lavfi \
      -i color=c=blue:s=160x120:d=1 \
      -pix_fmt yuv420p \
      -movflags +faststart \
      /tmp/overload_benchmark_test.mp4 >/dev/null 2>&1
    docker compose cp api:/tmp/overload_benchmark_test.mp4 "$GENERATED_VIDEO" >/dev/null
  fi
  export TEST_VIDEO_PATH="$GENERATED_VIDEO"
fi

PYTHON_BIN="${PYTHON_BIN:-python}"
if [[ "$PYTHON_BIN" == "python" && -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi

mkdir -p "$BENCHMARK_OUTPUT_DIR"
RUN_ID="$(date -u +%Y%m%d-%H%M%S)"

scenario_client_id() {
  local slot="$1"
  echo "10.250.$((RANDOM % 200 + 1)).$slot"
}

render_report() {
  local json_path="$1"
  local md_path="$2"
  "$PYTHON_BIN" scripts/render_benchmark_report.py --input "$json_path" --output "$md_path" >/dev/null
}

run_scenario() {
  local name="$1"
  local uploads="$2"
  local concurrency="$3"
  local client_id="$4"
  local poll_arg="$5"
  shift 5

  local json_path="${BENCHMARK_OUTPUT_DIR}/overload-${name}-${RUN_ID}.json"
  local md_path="${BENCHMARK_OUTPUT_DIR}/overload-${name}-${RUN_ID}.md"
  local latest_json="${BENCHMARK_OUTPUT_DIR}/latest-${name}.json"
  local latest_md="${BENCHMARK_OUTPUT_DIR}/latest-${name}.md"
  local args=(
    scripts/benchmark_uploads.py
    --base-url "$BASE_URL"
    --uploads "$uploads"
    --concurrency "$concurrency"
    --client-id "$client_id"
    --json-output "$json_path"
  )
  if [[ -n "${TEST_VIDEO_PATH:-}" ]]; then
    args+=(--video-path "$TEST_VIDEO_PATH")
  fi
  args+=("$poll_arg")

  echo
  echo "Running scenario: ${name}"
  "$PYTHON_BIN" "${args[@]}" "$@"

  cp "$json_path" "$latest_json"
  render_report "$json_path" "$md_path"
  cp "$md_path" "$latest_md"
  echo "Scenario report: $latest_md"
}

assert_baseline() {
  "$PYTHON_BIN" - "$BENCHMARK_OUTPUT_DIR/latest-baseline.json" <<'PY'
import json
import sys

summary = json.loads(open(sys.argv[1], encoding="utf-8").read())["summary"]
if summary["upload_rejection_count"] != 0 or summary["completed_jobs"] <= 0:
    raise SystemExit(f"baseline did not complete cleanly: {summary}")
PY
}

assert_worker_outage() {
  "$PYTHON_BIN" - "$BENCHMARK_OUTPUT_DIR/latest-worker-outage.json" <<'PY'
import json
import sys

summary = json.loads(open(sys.argv[1], encoding="utf-8").read())["summary"]
status_counts = summary.get("status_code_counts", {})
reason_counts = summary.get("rejection_reason_counts", {})
if int(status_counts.get("503", 0)) < 1 or int(reason_counts.get("insufficient_workers", 0)) < 1:
    raise SystemExit(f"worker outage did not produce 503 insufficient_workers: {summary}")
PY
}

check_rate_limit() {
  "$PYTHON_BIN" - "$BENCHMARK_OUTPUT_DIR/latest-rate-limit.json" <<'PY'
import json
import sys

summary = json.loads(open(sys.argv[1], encoding="utf-8").read())["summary"]
status_counts = summary.get("status_code_counts", {})
reason_counts = summary.get("rejection_reason_counts", {})
if int(status_counts.get("429", 0)) < 1 or int(reason_counts.get("rate_limited", 0)) < 1:
    print(f"WARNING: rate limit was not triggered in this local run: {summary}")
PY
}

run_scenario baseline 5 2 "$(scenario_client_id 11)" --poll
assert_baseline

echo
echo "Scaling workers to 0 for worker outage scenario"
docker compose up -d --scale worker=0
sleep 5
run_scenario worker-outage 2 1 "$(scenario_client_id 22)" --no-poll
assert_worker_outage

echo
echo "Restoring workers before rate-limit scenario"
docker compose up -d --scale worker=3 >/dev/null
sleep 5
run_scenario rate-limit 15 3 "$(scenario_client_id 33)" --no-poll
check_rate_limit

echo
echo "Docker Compose status"
docker compose ps

echo
echo "Dashboards:"
echo "  Grafana:    http://localhost:3000"
echo "  Prometheus: http://localhost:9090"
echo "  Jaeger:     http://localhost:16686"
