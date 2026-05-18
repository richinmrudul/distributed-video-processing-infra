# Distributed Video Processing Infrastructure

## Tests

Run fast tests without Docker:

```bash
PYTHONPATH=backend:. pytest backend/tests/unit -q
PYTHONPATH=backend:. pytest backend/tests/api -q
PYTHONPATH=backend:. pytest backend/tests -q
```
