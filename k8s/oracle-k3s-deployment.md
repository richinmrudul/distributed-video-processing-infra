# Oracle Always Free k3s Deployment Plan

## Purpose

Oracle Always Free plus k3s is the fully-free cloud deployment path for this project.

This is a self-managed Kubernetes deployment, not managed Kubernetes. Docker Compose remains the local development path, kind remains the local Kubernetes validation path, and GHCR images are used for cloud deployment.

## Architecture Target

Run on one Oracle Always Free Ampere A1 VM:

- k3s
- API Deployment
- Worker Deployment
- Reconciler Deployment
- Frontend Deployment
- Postgres Deployment for demo
- Redis Deployment for demo
- MinIO Deployment for demo
- Kubernetes Services

In-cluster Postgres, Redis, and MinIO are acceptable for a free portfolio demo. A production system should use managed Postgres, managed Redis, and durable cloud object storage. This Oracle path is not production HA.

## Oracle Account Prerequisites

- Oracle Cloud account
- Always Free eligible Ampere A1 shape availability
- Public subnet and security list rules
- SSH key pair
- Ubuntu image recommended
- Docker is not required on the VM for k3s deployment, but remains useful locally

## Suggested VM Shape

Use `VM.Standard.A1.Flex`.

Start with:

- 2 OCPUs
- 12 GB RAM

If available, 4 OCPUs and 24 GB RAM gives more headroom for FFmpeg workers, but it can be harder to provision. Stay inside Oracle Always Free limits and select Always Free eligible resources only.

## Required Open Ports

Start conservative:

- `22`: SSH
- `80`: HTTP later if exposing frontend/API publicly
- `443`: HTTPS later if adding TLS

Initially prefer SSH tunnels or `kubectl port-forward`. Do not expose admin endpoints publicly without the admin API key and additional network/reverse-proxy protection.

## Server Bootstrap Plan

SSH into the VM and run:

```bash
sudo apt-get update
sudo apt-get install -y curl ca-certificates git
curl -sfL https://get.k3s.io | sh -
sudo kubectl get nodes
sudo kubectl get pods -A
```

Or use the repo helper:

```bash
./scripts/bootstrap_oracle_k3s.sh
```

Install nginx ingress only if needed later. The first smoke test should use port-forwarding.

## Deployment Flow

1. Make GHCR packages public or configure an `imagePullSecret`.
2. Copy the repo to the VM or run `kubectl` remotely against the k3s cluster.
3. Prepare secrets:

   ```bash
   cp k8s/oracle-k3s.env.example k8s/oracle-k3s.env
   # edit k8s/oracle-k3s.env
   ./scripts/create_oracle_k3s_secret.sh
   ```

4. Apply the Oracle k3s overlay:

   ```bash
   ./scripts/oracle_k3s_apply.sh
   ```

5. Port-forward API and frontend first:

   ```bash
   kubectl -n video-processing port-forward svc/video-processing-api 18000:80
   kubectl -n video-processing port-forward svc/video-processing-frontend 13001:80
   ```

6. Run the deployed smoke test:

   ```bash
   BASE_URL=http://localhost:18000 ./scripts/deployed_smoke_test.sh
   ```

7. Later, add ingress, NodePort, or another exposure mechanism after the port-forward path is healthy.

## Image Strategy

The Oracle overlay uses GHCR images:

- `ghcr.io/richinmrudul/distributed-video-processing-infra-api:latest`
- `ghcr.io/richinmrudul/distributed-video-processing-infra-worker:latest`
- `ghcr.io/richinmrudul/distributed-video-processing-infra-reconciler:latest`
- `ghcr.io/richinmrudul/distributed-video-processing-infra-frontend:latest`

Use `latest` for the first demo. Prefer `sha-*` tags once the deployment is stable and you want reproducible notes.

If GHCR packages are private, create an image pull secret and patch `imagePullSecrets` into the workloads.

## Cost Control And Cleanup

- Verify all resources remain Always Free eligible.
- Avoid paid load balancers initially.
- Avoid extra block volumes beyond the free tier.
- Prefer port-forwarding before opening public ports.
- Stop or delete resources if unsure.
- Check the billing dashboard after deployment.

Delete the demo namespace:

```bash
kubectl delete namespace video-processing
```

Delete the VM if you no longer need the demo.
