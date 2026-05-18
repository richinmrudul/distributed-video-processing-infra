# Distributed Video Processing Infrastructure

## Tests

Run fast tests without Docker:

```bash
PYTHONPATH=backend:. pytest backend/tests/unit -q
PYTHONPATH=backend:. pytest backend/tests/api -q
PYTHONPATH=backend:. pytest backend/tests -q
```

Run Docker-backed integration tests:

```bash
./scripts/run_integration_tests.sh
```

The integration script starts Docker Compose and resets local Compose volumes unless `SKIP_COMPOSE_UP=1` is set.
