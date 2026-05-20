# Distributed Video Processing Infrastructure

## Container Images

GitHub Actions publishes Kubernetes-ready images to GitHub Container Registry:

- `ghcr.io/richinmrudul/distributed-video-processing-infra-api`
- `ghcr.io/richinmrudul/distributed-video-processing-infra-worker`
- `ghcr.io/richinmrudul/distributed-video-processing-infra-reconciler`
- `ghcr.io/richinmrudul/distributed-video-processing-infra-frontend`

Local Docker Compose still builds images locally. Kubernetes deployments can reference the GHCR images once packages are published and made public or paired with `imagePullSecrets`.
