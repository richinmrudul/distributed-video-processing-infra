#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

NAMESPACE="${NAMESPACE:-video-processing}"
OVERLAY="${ORACLE_K3S_OVERLAY:-k8s/overlays/oracle-k3s}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-300s}"

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl is required."
  exit 1
fi

echo "Current kubectl context:"
kubectl config current-context

if ! kubectl -n "$NAMESPACE" get secret video-processing-secrets >/dev/null 2>&1; then
  echo
  echo "Missing secret video-processing-secrets in namespace $NAMESPACE."
  echo "Create it first:"
  echo "  cp k8s/oracle-k3s.env.example k8s/oracle-k3s.env"
  echo "  # edit k8s/oracle-k3s.env"
  echo "  ./scripts/create_oracle_k3s_secret.sh"
  exit 1
fi

echo
echo "Applying Oracle k3s overlay: $OVERLAY"
kubectl kustomize --load-restrictor LoadRestrictionsNone "$OVERLAY" | kubectl apply -f -

echo
echo "Waiting for demo dependencies"
kubectl -n "$NAMESPACE" rollout status deployment/video-processing-postgres --timeout="$WAIT_TIMEOUT"
kubectl -n "$NAMESPACE" rollout status deployment/video-processing-redis --timeout="$WAIT_TIMEOUT"
kubectl -n "$NAMESPACE" rollout status deployment/video-processing-minio --timeout="$WAIT_TIMEOUT"
kubectl -n "$NAMESPACE" wait --for=condition=complete job/video-processing-minio-init --timeout="$WAIT_TIMEOUT"

echo
echo "Waiting for application workloads"
kubectl -n "$NAMESPACE" rollout status deployment/video-processing-api --timeout="$WAIT_TIMEOUT"
kubectl -n "$NAMESPACE" rollout status deployment/video-processing-worker --timeout="$WAIT_TIMEOUT"
kubectl -n "$NAMESPACE" rollout status deployment/video-processing-reconciler --timeout="$WAIT_TIMEOUT"
kubectl -n "$NAMESPACE" rollout status deployment/video-processing-frontend --timeout="$WAIT_TIMEOUT"

echo
echo "Pods:"
kubectl get pods -n "$NAMESPACE"

echo
echo "Services:"
kubectl get svc -n "$NAMESPACE"

echo
echo "Oracle k3s overlay applied."
echo "Port-forward to smoke test:"
echo "  kubectl -n $NAMESPACE port-forward svc/video-processing-api 18000:80"
echo "  BASE_URL=http://localhost:18000 ./scripts/deployed_smoke_test.sh"
