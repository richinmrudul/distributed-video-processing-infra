# Distributed Video Processing Infrastructure

## Database migrations (Alembic)

- Migrations run automatically when the **api** service starts (`alembic upgrade head` before Uvicorn).
- Create a new revision (from repo root, `PYTHONPATH=backend`):

  ```bash
  PYTHONPATH=backend alembic -c backend/alembic.ini revision --autogenerate -m "describe change"
  ```

- Apply manually:

  ```bash
  PYTHONPATH=backend alembic -c backend/alembic.ini upgrade head
  ```
