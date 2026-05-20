#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${ORACLE_K3S_ENV_FILE:-k8s/oracle-k3s.env}"
NAMESPACE="${NAMESPACE:-video-processing}"
SECRET_NAME="${SECRET_NAME:-video-processing-secrets}"

SECRET_KEYS=(
  DATABASE_URL
  REDIS_URL
  ADMIN_API_KEY
  OBJECT_STORAGE_ENDPOINT
  OBJECT_STORAGE_PUBLIC_ENDPOINT
  OBJECT_STORAGE_ACCESS_KEY
  OBJECT_STORAGE_SECRET_KEY
  OBJECT_STORAGE_REGION
  OBJECT_STORAGE_SECURE
)

PLACEHOLDER_PATTERNS=(
  "replace-"
  "replace-with"
  "replace-me"
  "REPLACE_WITH"
  "dev-admin-key"
)

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl is required to create the Kubernetes secret."
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE."
  echo "Copy k8s/oracle-k3s.env.example to $ENV_FILE and replace every placeholder first."
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

missing=()
placeholder_keys=()

for key in "${SECRET_KEYS[@]}"; do
  value="${!key:-}"
  if [[ -z "$value" ]]; then
    missing+=("$key")
    continue
  fi
  for pattern in "${PLACEHOLDER_PATTERNS[@]}"; do
    if [[ "$value" == *"$pattern"* ]]; then
      placeholder_keys+=("$key")
      break
    fi
  done
done

if (( ${#missing[@]} > 0 )); then
  echo "Missing required secret keys: ${missing[*]}"
  exit 1
fi

if (( ${#placeholder_keys[@]} > 0 )); then
  echo "Refusing to create $SECRET_NAME because placeholders remain for: ${placeholder_keys[*]}"
  exit 1
fi

echo "Creating/updating Kubernetes secret $SECRET_NAME in namespace $NAMESPACE."
echo "Including keys: ${SECRET_KEYS[*]}"

kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

secret_env_file="$(mktemp -t oracle-k3s-secret-XXXXXX.env)"
cleanup() {
  rm -f "$secret_env_file"
}
trap cleanup EXIT
chmod 600 "$secret_env_file"

for key in "${SECRET_KEYS[@]}"; do
  printf '%s=%s\n' "$key" "${!key}" >>"$secret_env_file"
done

kubectl -n "$NAMESPACE" create secret generic "$SECRET_NAME" \
  --from-env-file="$secret_env_file" \
  --dry-run=client \
  -o yaml | kubectl apply -f -

echo "Secret $SECRET_NAME applied. Secret values were not printed."
