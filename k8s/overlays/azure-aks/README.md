# Azure AKS Demo Overlay

This overlay reproduces the working AKS browser demo path:

frontend upload -> FastAPI upload endpoint -> Redis/RQ queue -> worker FFmpeg processing -> MinIO object storage -> `COMPLETED` status -> presigned processed video and thumbnail URLs in the UI.

It is a demo overlay for local port-forward access on AKS. It does not create Azure resources, public ingress, TLS, or real secrets.

## Start Or Stop AKS

Start the existing AKS cluster:

```bash
az aks start \
  --resource-group rg-video-processing-demo \
  --name aks-video-processing-demo
```

Stop the cluster when you are done testing:

```bash
az aks stop \
  --resource-group rg-video-processing-demo \
  --name aks-video-processing-demo
```

Fetch kubeconfig:

```bash
az aks get-credentials \
  --resource-group rg-video-processing-demo \
  --name aks-video-processing-demo \
  --overwrite-existing
```

## Create Required Secret

Create the namespace first:

```bash
kubectl apply -f k8s/namespace.yaml
```

Create the secret with demo-only values. Replace every `<change-me>` before applying:

```bash
kubectl create secret generic video-processing-secrets \
  -n video-processing \
  --from-literal=ADMIN_API_KEY='<change-me>' \
  --from-literal=DATABASE_URL='postgresql+psycopg2://video:video@video-processing-postgres:5432/video' \
  --from-literal=REDIS_URL='redis://video-processing-redis:6379/0' \
  --from-literal=OBJECT_STORAGE_ACCESS_KEY='<change-me>' \
  --from-literal=OBJECT_STORAGE_SECRET_KEY='<change-me>'
```

Do not commit real secret values.

## Apply Overlay

Render check:

```bash
kubectl kustomize k8s/overlays/azure-aks --load-restrictor=LoadRestrictionsNone
```

Apply:

```bash
kubectl kustomize k8s/overlays/azure-aks --load-restrictor=LoadRestrictionsNone | kubectl apply -f -
```

Wait for workloads:

```bash
kubectl -n video-processing rollout status deployment/video-processing-postgres
kubectl -n video-processing rollout status deployment/video-processing-redis
kubectl -n video-processing rollout status deployment/video-processing-minio
kubectl -n video-processing wait --for=condition=complete job/video-processing-minio-init --timeout=180s
kubectl -n video-processing rollout status deployment/video-processing-api
kubectl -n video-processing rollout status deployment/video-processing-worker
kubectl -n video-processing rollout status deployment/video-processing-reconciler
kubectl -n video-processing rollout status deployment/video-processing-frontend
```

The MinIO init job creates these buckets and is safe to re-run:

- `raw-videos`
- `processed-videos`
- `thumbnails`

## Local Port Forward Demo

Run these in separate terminals:

```bash
kubectl port-forward -n video-processing svc/video-processing-api 8000:80
kubectl port-forward -n video-processing svc/video-processing-frontend 3000:80
kubectl port-forward -n video-processing svc/video-processing-minio 9000:9000
```

Open the browser demo:

```text
http://localhost:3000
```

## Smoke Tests

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/v1/queue/health
curl http://localhost:8000/api/v1/storage/health
```

Expected:

- API health returns `200`
- queue health reports Redis connected
- storage health reports MinIO reachable

## Cleanup

Delete only the Kubernetes namespace:

```bash
kubectl delete namespace video-processing
```

Delete the Azure resource group when the demo is no longer needed:

```bash
az group delete --name rg-video-processing-demo --yes --no-wait
```
