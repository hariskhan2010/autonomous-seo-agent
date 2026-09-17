# 0003 — Celery + Temporal, distinct non-overlapping roles

- Status: accepted
- Date: 2026-09-06
- Supersedes the earlier "Celery now, migrate to Temporal later" note.

## Context
Two very different workloads: (a) short, stateless, retryable unit jobs (a crawl batch, a SERP
pull, an embedding job); (b) the long autonomous loop that runs for hours-to-days, waits at
human approval gates, and must survive deploys and crashes (A-TO-Z-PLAN.md §AA, §J).

## Decision
Use **both**, with fixed roles and no overlap:
- **Celery + Redis** — all short (<~15 min) unit jobs. Retries, rate-limits, backpressure. Not a
  workflow engine; never used to hold multi-step state.
- **Celery beat** — time-based triggers only; enqueues jobs / starts workflows.
- **Temporal** (from Phase 11) — the autonomous loop: durable state, crash-resume, per-activity
  timeouts, approval waits via signals, deterministic replay. Its activities call Celery jobs/tools.

Phase 11 builds the loop on Temporal directly — no interim DB-polling state machine on Celery.

## Consequences
- Two runtimes to operate. Temporal self-hosted (docker-compose) in dev, Temporal Cloud in prod.
- Clear ownership: if it needs durable multi-step state, it's a Temporal workflow; otherwise a
  Celery task.

## Alternatives considered
- Celery-only with a DB state machine: rejected — reinvents Temporal badly (no replay, fragile
  recovery, manual timeouts).
- Temporal-only: rejected — overkill for high-volume fan-out unit jobs.
