# autonomous-seo-agent

An SEO operating system that runs the loop
`OBSERVE → CRAWL → UNDERSTAND → RESEARCH → DETECT → PRIORITIZE → PLAN → EXECUTE → VERIFY → MEASURE → LEARN → REPEAT`
where every action produces evidence and every change is traceable, auditable, reversible,
verifiable, and idempotent.

- **Vision:** `../Plan.md — Autonomous SEO Agent.md`
- **Build bible:** `../A-TO-Z-PLAN.md` (V2)
- **Status:** Phase 0 — architecture & scaffolding

## Layout

| Path | What |
|---|---|
| `apps/api` | FastAPI — REST surface (`/v1`), auth, tenant middleware |
| `apps/worker` | Task worker (Celery now; Temporal for the long loop from Phase 11) |
| `apps/dashboard` | Next.js dashboard on the `/v1` read API (Phase 12 — not built) |
| `packages/seo_core` | Deterministic analyzers (ported from the original prototype) |
| `packages/llm` | Provider abstraction + logical-role model router + cost meter |
| `packages/tools` | Tool registry — the only way agents touch the world |
| `packages/*` | knowledge_graph, opportunity_engine, planner, execution, verification, rollback, memory, experiments, events |
| `integrations/` | gsc, analytics, cms, serp, backlinks, ai_providers |
| `mcp/` | MCP servers wrapping external systems |
| `database/` | Alembic migrations, seed, ERD |
| `tests/` | unit / integration / e2e / eval harness |
| `docs/` | ARCHITECTURE, DATABASE, TOOLS, SECURITY, AGENTS, API, EVALUATION, DEPLOYMENT, BUILD-LOG |
| `docs/adr/` | Architecture Decision Records |

## Quick start (dev)

```bash
cp .env.example .env          # fill DATABASE_URL, REDIS_URL, ANTHROPIC_API_KEY at minimum
docker compose -f infra/docker-compose.yml up -d db redis minio
uv sync
uv run alembic -c database/alembic.ini upgrade head
uv run uvicorn app.main:app --app-dir apps/api --reload
```

Health: `http://localhost:8000/v1/health` · OpenAPI: `http://localhost:8000/docs`

## Toolchain

Python 3.13 · [uv](https://docs.astral.sh/uv/) · FastAPI · SQLAlchemy 2 + Alembic · Postgres 16 +
pgvector + pg_trgm · Redis · Celery · MinIO (S3) · OpenTelemetry.
