# Distributed Video Processing Infrastructure

## Demo Console

Run the local stack with workers, then open the lightweight frontend console:

```bash
docker compose up --build --scale worker=3
```

- Frontend: `http://localhost:3001`
- API base URL: `http://localhost:8000`
- Admin dev key: `dev-admin-key`

Demo flow: upload a video, watch status polling, view completed assets, then inspect failed or stuck jobs from the Admin Operations panel.
