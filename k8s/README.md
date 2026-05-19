# Kubernetes Readiness Manifests

These manifests show how to run the API, RQ workers, and reconciler as independent Kubernetes workloads. They are readiness scaffolding, not a complete production deployment.

Docker Compose remains the source of truth for local development.

## Apply Order

```bash
kubectl apply -f namespace.yaml
kubectl apply -f configmap.yaml
cp secrets.example.yaml secrets.yaml
# edit secrets.yaml and replace every placeholder
kubectl apply -f secrets.yaml
kubectl apply -f api-deployment.yaml -f api-service.yaml
kubectl apply -f worker-deployment.yaml
kubectl apply -f reconciler-deployment.yaml
```

From the repo root:

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
cp k8s/secrets.example.yaml k8s/secrets.yaml
kubectl apply -f k8s/secrets.yaml
kubectl apply -f k8s/api-deployment.yaml -f k8s/api-service.yaml
kubectl apply -f k8s/worker-deployment.yaml
kubectl apply -f k8s/reconciler-deployment.yaml
```

## Scaling

```bash
kubectl -n video-processing scale deployment/video-processing-worker --replicas=5
kubectl -n video-processing scale deployment/video-processing-api --replicas=3
```

The reconciler defaults to one replica. The Redis lock protects against duplicate reconciler work, but keep the default at one unless you are explicitly testing failover behavior.

## Production Notes

- Use managed Postgres.
- Use managed Redis.
- Use S3 or S3-compatible object storage.
- Store secrets in a real secret manager and generate `video-processing-secrets` from that source.
- Run Alembic migrations as a separate Kubernetes Job before rolling out API replicas. The Kubernetes API deployment intentionally runs only `uvicorn`.
- Add Ingress and TLS later.
- Add HPA later.
- Add Prometheus Operator `ServiceMonitor` resources later.
- The worker and reconciler manifests use the same application image as the API and override the command.
