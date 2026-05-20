#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

KIND_CLUSTER_NAME="${KIND_CLUSTER_NAME:-video-processing-smoke}"
NAMESPACE="${NAMESPACE:-video-processing}"
API_LOCAL_PORT="${API_LOCAL_PORT:-18000}"
FRONTEND_LOCAL_PORT="${FRONTEND_LOCAL_PORT:-13001}"

API_IMAGE="distributed-video-processing-infra-api:kind"
WORKER_IMAGE="distributed-video-processing-infra-worker:kind"
RECONCILER_IMAGE="distributed-video-processing-infra-reconciler:kind"
FRONTEND_IMAGE="distributed-video-processing-infra-frontend:kind"

PORT_FORWARD_PIDS=()

cleanup() {
  for pid in "${PORT_FORWARD_PIDS[@]:-}"; do
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
    fi
  done
}
trap cleanup EXIT

require_command() {
  local cmd="$1"
  local install_hint="$2"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "$cmd is required for the kind smoke test."
    echo "$install_hint"
    exit 1
  fi
}

wait_for_http() {
  local url="$1"
  echo "Waiting for $url"
  for _ in {1..60}; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  curl -fsS "$url" >/dev/null
}

port_forward() {
  local service="$1"
  local mapping="$2"
  kubectl -n "$NAMESPACE" port-forward "$service" "$mapping" >/tmp/"${service##*/}-port-forward.log" 2>&1 &
  PORT_FORWARD_PIDS+=("$!")
}

require_command docker "Install Docker Desktop or Docker Engine and ensure the daemon is running."
require_command kind "Install kind: https://kind.sigs.k8s.io/docs/user/quick-start/#installation"
require_command kubectl "Install kubectl: https://kubernetes.io/docs/tasks/tools/"
require_command curl "Install curl or run from a shell where curl is available."

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not reachable."
  exit 1
fi

if ! kind get clusters | grep -qx "$KIND_CLUSTER_NAME"; then
  echo "Creating kind cluster: $KIND_CLUSTER_NAME"
  kind create cluster --name "$KIND_CLUSTER_NAME"
else
  echo "Using existing kind cluster: $KIND_CLUSTER_NAME"
fi

kubectl config use-context "kind-${KIND_CLUSTER_NAME}" >/dev/null

echo "Building local backend image"
docker build -f backend/Dockerfile -t "$API_IMAGE" .
docker tag "$API_IMAGE" "$WORKER_IMAGE"
docker tag "$API_IMAGE" "$RECONCILER_IMAGE"

echo "Building local frontend image"
docker build --build-arg NEXT_PUBLIC_API_BASE_URL="http://localhost:${API_LOCAL_PORT}" -t "$FRONTEND_IMAGE" ./frontend

echo "Loading images into kind"
kind load docker-image "$API_IMAGE" --name "$KIND_CLUSTER_NAME"
kind load docker-image "$WORKER_IMAGE" --name "$KIND_CLUSTER_NAME"
kind load docker-image "$RECONCILER_IMAGE" --name "$KIND_CLUSTER_NAME"
kind load docker-image "$FRONTEND_IMAGE" --name "$KIND_CLUSTER_NAME"

echo "Applying kind overlay"
kubectl kustomize --load-restrictor LoadRestrictionsNone k8s/overlays/kind | kubectl apply -f -

echo "Waiting for local-kind dependencies"
kubectl -n "$NAMESPACE" rollout status deployment/video-processing-postgres --timeout=180s
kubectl -n "$NAMESPACE" rollout status deployment/video-processing-redis --timeout=180s
kubectl -n "$NAMESPACE" rollout status deployment/video-processing-minio --timeout=180s
kubectl -n "$NAMESPACE" wait --for=condition=complete job/video-processing-minio-init --timeout=180s

echo "Waiting for application workloads"
kubectl -n "$NAMESPACE" rollout status deployment/video-processing-api --timeout=240s
kubectl -n "$NAMESPACE" rollout status deployment/video-processing-worker --timeout=240s
kubectl -n "$NAMESPACE" rollout status deployment/video-processing-reconciler --timeout=240s
kubectl -n "$NAMESPACE" rollout status deployment/video-processing-frontend --timeout=240s

port_forward "svc/video-processing-api" "${API_LOCAL_PORT}:80"
port_forward "svc/video-processing-frontend" "${FRONTEND_LOCAL_PORT}:80"

wait_for_http "http://localhost:${API_LOCAL_PORT}/health"
curl -fsS "http://localhost:${API_LOCAL_PORT}/api/v1/queue/health" | grep -q '"redis_connected":true'

if [[ "${RUN_KIND_UPLOAD_SMOKE:-0}" == "1" ]]; then
  if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "RUN_KIND_UPLOAD_SMOKE=1 requires local ffmpeg; skipping upload smoke."
  else
    tmp_video="$(mktemp -t kind-smoke-video-XXXXXX.mp4)"
    ffmpeg -y -f lavfi -i color=c=blue:s=160x120:d=1 -pix_fmt yuv420p -movflags +faststart "$tmp_video" >/dev/null 2>&1
    upload_body="$(curl -fsS -X POST "http://localhost:${API_LOCAL_PORT}/api/v1/videos/upload" -F "file=@${tmp_video};type=video/mp4")"
    video_id="$(python -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$upload_body")"
    python - "$API_LOCAL_PORT" "$video_id" <<'PY'
import json
import sys
import time
from urllib.request import urlopen

port, video_id = sys.argv[1], sys.argv[2]
deadline = time.time() + 90
last = None
while time.time() < deadline:
    with urlopen(f"http://localhost:{port}/api/v1/videos/{video_id}/status", timeout=5) as resp:
        body = json.loads(resp.read().decode())
    last = body.get("status")
    if last in {"COMPLETED", "FAILED"}:
        print(f"upload_smoke_status={last}")
        sys.exit(0)
    time.sleep(2)
raise SystemExit(f"upload smoke did not reach terminal status; last={last}")
PY
  fi
fi

echo
echo "kind smoke test succeeded."
echo "API:      http://localhost:${API_LOCAL_PORT}"
echo "Frontend: http://localhost:${FRONTEND_LOCAL_PORT}"
echo
echo "Port-forwards will stop when this script exits."
