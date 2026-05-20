# Civo Kubernetes Deployment Plan

## Purpose

Civo is the first real managed Kubernetes target for this project. This document is a cloud deployment plan, not the local development path.

Docker Compose remains the primary local workflow. The kind smoke test remains the local Kubernetes validation path.

## Architecture Target

Run in Civo Kubernetes:

- API Deployment
- Worker Deployment
- Reconciler Deployment
- Frontend Deployment
- Kubernetes Services
- Optional Ingress or LoadBalancer after the first port-forward smoke test

Use external or managed dependencies where possible:

| Dependency | Recommended Civo/cloud mapping |
| --- | --- |
| Postgres | Managed Postgres if available and affordable; temporary in-cluster Postgres only for short demos |
| Redis | Managed Redis if available and affordable; temporary in-cluster Redis only for short demos |
| Object storage | Civo Object Store or another S3-compatible provider; demo MinIO only for short tests |
| Observability | Optional initially; local Grafana/Prometheus remain primary until cloud observability is configured |

## Civo Account Prerequisites

- Civo account with billing or trial credits understood
- `kubectl` installed
- Civo CLI installed if using CLI
- Access to GHCR images
- GHCR packages made public, or Kubernetes `imagePullSecrets` configured

Civo Kubernetes can be created from the dashboard or CLI:

- https://www.civo.com/docs/kubernetes/create-a-cluster
- https://www.civo.com/docs/overview/civo-cli

## Suggested Cluster Settings

Start small:

- 1 node initially
- Cheapest viable region and size for the demo
- Scale only when testing worker throughput or availability
- Delete the cluster when not testing to control cost

Check the Civo dashboard and pricing page before creating resources. Do not assume a fixed price from this repo.

## Secrets And Env Vars

Copy `k8s/civo.env.example` to `k8s/civo.env` and replace every placeholder before creating the Kubernetes Secret.

Important values:

- `DATABASE_URL`
- `REDIS_URL`
- `OBJECT_STORAGE_ENDPOINT`
- `OBJECT_STORAGE_PUBLIC_ENDPOINT`
- `OBJECT_STORAGE_ACCESS_KEY`
- `OBJECT_STORAGE_SECRET_KEY`
- `ADMIN_API_KEY`
- `RAW_VIDEO_BUCKET`
- `PROCESSED_VIDEO_BUCKET`
- `THUMBNAIL_BUCKET`
- `CORS_ALLOWED_ORIGINS`
- `NEXT_PUBLIC_API_BASE_URL`

Never commit `k8s/civo.env`.

## Image Strategy

Use GHCR images:

- `ghcr.io/richinmrudul/distributed-video-processing-infra-api:latest`
- `ghcr.io/richinmrudul/distributed-video-processing-infra-worker:latest`
- `ghcr.io/richinmrudul/distributed-video-processing-infra-reconciler:latest`
- `ghcr.io/richinmrudul/distributed-video-processing-infra-frontend:latest`

`latest` is acceptable for a first demo. Prefer `sha-*` tags for reproducible deployment notes, debugging, and resume screenshots.

If GHCR packages are private, create an image pull secret:

```bash
kubectl -n video-processing create secret docker-registry ghcr-pull-secret \
  --docker-server=ghcr.io \
  --docker-username="$GITHUB_USERNAME" \
  --docker-password="$GITHUB_TOKEN"
```

Then add `imagePullSecrets` to the workloads or patch them in a deployment-specific overlay.

## Deployment Flow

1. Create the Civo cluster from the dashboard or CLI.
2. Connect `kubectl` to the Civo cluster context.
3. Create the namespace:

   ```bash
   kubectl apply -f k8s/namespace.yaml
   ```

4. Create the Kubernetes Secret from `k8s/civo.env`:

   ```bash
   cp k8s/civo.env.example k8s/civo.env
   # edit k8s/civo.env
   ./scripts/create_civo_k8s_secret.sh
   ```

5. Apply configuration and workloads:

   ```bash
   kubectl apply -f k8s/configmap.yaml
   kubectl apply -f k8s/api-deployment.yaml -f k8s/api-service.yaml
   kubectl apply -f k8s/worker-deployment.yaml
   kubectl apply -f k8s/reconciler-deployment.yaml
   ```

   Or render the GHCR demo overlay:

   ```bash
   kubectl kustomize --load-restrictor LoadRestrictionsNone k8s/overlays/ghcr | kubectl apply -f -
   ```

6. Wait for deployments:

   ```bash
   kubectl -n video-processing rollout status deployment/video-processing-api
   kubectl -n video-processing rollout status deployment/video-processing-worker
   kubectl -n video-processing rollout status deployment/video-processing-reconciler
   ```

7. Port-forward first:

   ```bash
   kubectl -n video-processing port-forward svc/video-processing-api 18000:80
   ```

8. Run the deployed smoke test:

   ```bash
   BASE_URL=http://localhost:18000 ./scripts/deployed_smoke_test.sh
   ```

9. Add Ingress or LoadBalancer only after the port-forward smoke test is healthy.

## Cleanup

Delete repo-managed resources:

```bash
kubectl delete namespace video-processing
```

For cost control, delete the Civo cluster when the demo is finished.

Avoid pasting secrets into commands that remain in shell history. Prefer editing `k8s/civo.env` locally and generating the Kubernetes Secret from the helper script.
