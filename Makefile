.PHONY: up down up-temporal sync lint type test migrate api worker temporal-worker fmt

up:       ; docker compose -f infra/docker-compose.yml up -d db redis minio
# Adds the self-hosted Temporal dev server + UI (ADR-0003, the durable autonomous loop).
up-temporal: ; docker compose -f infra/docker-compose.yml up -d db redis minio temporal temporal-ui
down:     ; docker compose -f infra/docker-compose.yml down
sync:     ; uv sync
lint:     ; uv run ruff check .
fmt:      ; uv run ruff format . && uv run ruff check --fix .
type:     ; uv run mypy packages apps integrations
test:     ; uv run pytest
migrate:  ; uv run alembic -c database/alembic.ini upgrade head
# PYTHONPATH matches infra/Dockerfile.api's — without it, `integrations` (a top-level package,
# not under packages/apps/api/apps/worker) fails to import outside the container.
api:      ; PYTHONPATH=$$PWD:$$PWD/packages:$$PWD/apps/api:$$PWD/apps/worker uv run uvicorn app.main:app --app-dir apps/api --reload
worker:   ; PYTHONPATH=$$PWD:$$PWD/packages:$$PWD/apps/api:$$PWD/apps/worker uv run celery -A worker.app.celery_app worker -l INFO
temporal-worker: ; PYTHONPATH=$$PWD:$$PWD/packages:$$PWD/apps/api:$$PWD/apps/worker uv run python -m worker.temporal.run_worker
