#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BASE_URL="${TEST_API_BASE_URL:-http://localhost:8000}"

if [[ "${SKIP_COMPOSE_UP:-0}" != "1" ]]; then
  docker compose down -v
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
  GENERATED_VIDEO="/tmp/distributed-video-processing-integration-test.mp4"
  if [[ ! -f "$GENERATED_VIDEO" ]]; then
    docker compose exec -T api ffmpeg \
      -y \
      -f lavfi \
      -i color=c=blue:s=160x120:d=1 \
      -pix_fmt yuv420p \
      -movflags +faststart \
      /tmp/integration_test.mp4 >/dev/null 2>&1
    docker compose cp api:/tmp/integration_test.mp4 "$GENERATED_VIDEO" >/dev/null
  fi
  export TEST_VIDEO_PATH="$GENERATED_VIDEO"
fi

PYTEST_BIN="${PYTEST_BIN:-pytest}"
if [[ "${PYTEST_BIN}" == "pytest" && -x ".venv/bin/pytest" ]]; then
  PYTEST_BIN=".venv/bin/pytest"
fi

PYTHONPATH=backend:. "$PYTEST_BIN" backend/tests/integration -q
