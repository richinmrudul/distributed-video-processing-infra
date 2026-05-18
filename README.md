# Distributed Video Processing Infrastructure

## Tests

Fast Tests run automatically in GitHub Actions on pushes and pull requests to `master`.

```bash
PYTHONPATH=backend:. pytest backend/tests -q -m "not integration"
```

Docker-backed integration tests are manual. Run them locally with:

```bash
./scripts/run_integration_tests.sh
```

The script starts Docker Compose and may reset local Compose volumes. In GitHub Actions, the `Integration Tests` workflow is manual-only via `workflow_dispatch`.

