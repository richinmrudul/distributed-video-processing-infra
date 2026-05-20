#!/usr/bin/env bash
set -Eeuo pipefail

echo "Oracle Always Free k3s bootstrap"
echo "This script installs local packages and k3s on the current VM only."
echo "It does not create Oracle Cloud resources, load balancers, ingress, or secrets."

if [[ "$(id -u)" -eq 0 ]]; then
  SUDO=""
else
  SUDO="sudo"
fi

if command -v k3s >/dev/null 2>&1; then
  echo "k3s is already installed; skipping installation."
else
  echo "Installing base packages: curl ca-certificates git"
  $SUDO apt-get update
  $SUDO apt-get install -y curl ca-certificates git

  echo "Installing k3s with the official installer"
  curl -sfL https://get.k3s.io | $SUDO sh -
fi

echo "Waiting for k3s node readiness"
for _ in {1..60}; do
  if $SUDO kubectl get nodes >/dev/null 2>&1; then
    if $SUDO kubectl wait --for=condition=Ready node --all --timeout=10s >/dev/null 2>&1; then
      break
    fi
  fi
  sleep 2
done

echo
echo "Nodes:"
$SUDO kubectl get nodes

echo
echo "System pods:"
$SUDO kubectl get pods -A

echo
echo "k3s bootstrap complete."
echo "Use sudo kubectl on this VM, or copy /etc/rancher/k3s/k3s.yaml to your workstation and adjust the server address."
