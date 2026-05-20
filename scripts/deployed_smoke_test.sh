#!/usr/bin/env bash
set -Eeuo pipefail

BASE_URL="${BASE_URL:-http://localhost:18000}"
ADMIN_API_KEY="${ADMIN_API_KEY:-}"
RUN_UPLOAD_SMOKE="${RUN_UPLOAD_SMOKE:-0}"
TEST_VIDEO_PATH="${TEST_VIDEO_PATH:-}"
SMOKE_TIMEOUT_SECONDS="${SMOKE_TIMEOUT_SECONDS:-120}"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required for the deployed smoke test."
  exit 1
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "python3 or python is required for JSON parsing."
  exit 1
fi

BASE_URL="${BASE_URL%/}"

request() {
  local path="$1"
  curl -fsS "${BASE_URL}${path}"
}

echo "Checking deployed API at $BASE_URL"

request "/health" >/dev/null
echo "health: ok"

queue_body="$(request "/api/v1/queue/health")"
echo "$queue_body" | "$PYTHON_BIN" -c '
import json
import sys

body = json.load(sys.stdin)
connected = body.get("redis_connected")
if connected is not True:
    raise SystemExit(f"queue health did not report redis_connected=true: {connected!r}")
print("queue health: redis_connected=true")
'

storage_body="$(request "/api/v1/storage/health")"
echo "$storage_body" | "$PYTHON_BIN" -c '
import json
import sys

body = json.load(sys.stdin)
status = body.get("status") or body.get("healthy") or body.get("connected")
if status in (False, "error", "unhealthy"):
    raise SystemExit(f"storage health looked unhealthy: {status!r}")
print("storage health: reachable")
'

if [[ -n "$ADMIN_API_KEY" ]]; then
  curl -fsS -H "X-Admin-API-Key: ${ADMIN_API_KEY}" "${BASE_URL}/api/v1/jobs/failed" >/dev/null
  echo "admin failed-jobs endpoint: reachable"
else
  echo "admin endpoint check skipped; set ADMIN_API_KEY to enable it."
fi

if [[ "$RUN_UPLOAD_SMOKE" == "1" ]]; then
  generated_video=""
  if [[ -z "$TEST_VIDEO_PATH" ]]; then
    if ! command -v ffmpeg >/dev/null 2>&1; then
      echo "RUN_UPLOAD_SMOKE=1 requires TEST_VIDEO_PATH or local ffmpeg."
      exit 1
    fi
    generated_video="$(mktemp -t deployed-smoke-video-XXXXXX.mp4)"
    ffmpeg -y -f lavfi -i color=c=blue:s=160x120:d=1 -pix_fmt yuv420p -movflags +faststart "$generated_video" >/dev/null 2>&1
    TEST_VIDEO_PATH="$generated_video"
  fi

  if [[ ! -f "$TEST_VIDEO_PATH" ]]; then
    echo "TEST_VIDEO_PATH does not exist: $TEST_VIDEO_PATH"
    exit 1
  fi

  upload_body="$(curl -fsS -X POST "${BASE_URL}/api/v1/videos/upload" -F "file=@${TEST_VIDEO_PATH};type=video/mp4")"
  video_id="$(echo "$upload_body" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
  echo "upload smoke: submitted video job $video_id"

  "$PYTHON_BIN" - "$BASE_URL" "$video_id" "$SMOKE_TIMEOUT_SECONDS" <<'PY'
import json
import sys
import time
from urllib.request import urlopen

base_url, video_id, timeout = sys.argv[1], sys.argv[2], int(sys.argv[3])
deadline = time.time() + timeout
last = None
while time.time() < deadline:
    with urlopen(f"{base_url}/api/v1/videos/{video_id}/status", timeout=10) as response:
        body = json.loads(response.read().decode())
    last = body.get("status")
    if last in {"COMPLETED", "FAILED"}:
        print(f"upload smoke: terminal status={last}")
        sys.exit(0)
    time.sleep(2)
raise SystemExit(f"upload smoke timed out; last status={last}")
PY
else
  echo "upload smoke skipped; set RUN_UPLOAD_SMOKE=1 to enable it."
fi

echo "deployed smoke test succeeded."
