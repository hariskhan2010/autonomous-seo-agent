.PHONY: up down up-temporal temporal-dev sync lint type test migrate api worker beat temporal-worker fmt

up:       ; docker compose -f infra/docker-compose.yml up -d db redis minio
# Adds the Temporal dev server + its UI on :8080 (ADR-0003, the durable autonomous loop).
up-temporal: ; docker compose -f infra/docker-compose.yml up -d db redis minio temporal
# Same dev server with no Docker at all — needs the Temporal CLI (https://temporal.io/setup/install-temporal-cli).
temporal-dev: ; temporal server start-dev --db-filename .temporal-dev.db
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
# Phase 11 periodic trigger (scheduler.tick + events.relay). Run ONE instance; targets/intervals
# come from BEAT_TARGETS / BEAT_*_SECONDS (see packages/common/settings.py, worker/beat.py).
beat:     ; PYTHONPATH=$$PWD:$$PWD/packages:$$PWD/apps/api:$$PWD/apps/worker uv run celery -A worker.app.celery_app beat -l INFO
temporal-worker: ; PYTHONPATH=$$PWD:$$PWD/packages:$$PWD/apps/api:$$PWD/apps/worker uv run python -m worker.temporal.run_worker
