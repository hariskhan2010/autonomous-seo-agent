# Deployment

Full runbook is written in Phase 13. This is the current (Phase 0) state.

## Local dev
```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up -d db redis minio
uv sync
uv run alembic -c database/alembic.ini upgrade head   # no-op until migration 0001
uv run uvicorn app.main:app --app-dir apps/api --reload
uv run celery -A worker.app.celery_app worker -l INFO   # separate shell
```

## Environments
| Env | DB | Object store | Workflow | Secrets |
|---|---|---|---|---|
| dev | Docker pgvector | MinIO | Celery only | `.env` |
| staging | Neon branch | R2 bucket | Celery + Temporal (self-host) | secret manager |
| prod | Neon (Launch+) | R2 / S3 | Celery + Temporal Cloud | secret manager |

## CI
`.github/workflows/ci.yml` — ruff, mypy, `alembic upgrade head`, pytest + coverage, against
ephemeral Postgres + Redis services.

## Release
Tag `v0.MINOR.0` per milestone. `v0.1.0-foundation` after Phase 1.

## Backups
Neon PITR (history retention). Object storage lifecycle + versioning. Restore drill in Phase 13.
