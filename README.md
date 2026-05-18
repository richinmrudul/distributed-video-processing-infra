# Distributed Video Processing Infrastructure

## Tests

Fast tests run in GitHub Actions on pushes and pull requests to `master`.

```bash
PYTHONPATH=backend:. pytest backend/tests/unit -q
PYTHONPATH=backend:. pytest backend/tests/api -q
PYTHONPATH=backend:. pytest backend/tests -q -m "not integration"
```

Docker-backed integration tests are manual for now:

```bash
./scripts/run_integration_tests.sh
```

The `Integration Tests` workflow is `workflow_dispatch` only.
