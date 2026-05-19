#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl not found; skipping Kubernetes dry-run validation."
  echo "Manifests are in k8s/. Install kubectl to run client-side validation."
  exit 0
fi

if ! kubectl version --request-timeout=3s >/dev/null 2>&1; then
  echo "kubectl is installed, but no Kubernetes API is reachable from this environment."
  echo "Skipping dry-run validation; inspect k8s/*.yaml or run this script with cluster access."
  exit 0
fi

kubectl apply --dry-run=client --validate=false -f k8s/namespace.yaml
kubectl apply --dry-run=client --validate=false -f k8s/configmap.yaml
kubectl apply --dry-run=client --validate=false -f k8s/secrets.example.yaml
kubectl apply --dry-run=client --validate=false -f k8s/api-deployment.yaml
kubectl apply --dry-run=client --validate=false -f k8s/api-service.yaml
kubectl apply --dry-run=client --validate=false -f k8s/worker-deployment.yaml
kubectl apply --dry-run=client --validate=false -f k8s/reconciler-deployment.yaml
