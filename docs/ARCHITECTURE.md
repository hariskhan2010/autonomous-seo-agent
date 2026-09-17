# Architecture

Authoritative narrative: `../A-TO-Z-PLAN.md` Parts II–IV. This file is the quick map.

## The loop
`OBSERVE → CRAWL → UNDERSTAND → RESEARCH → DETECT → PRIORITIZE → PLAN → EXECUTE → VERIFY →
MEASURE → LEARN → REPEAT`, implemented as the `agent_runs` state machine (§J), driven by the
Orchestrator (Temporal workflow, Phase 11).

## Pillars (non-negotiable)
1. Evidence first — every finding cites ≥1 hashed, provider-attributed `evidence` row.
2. Deterministic tools + probabilistic intelligence — Python for facts, LLMs for judgment (§V).
3. Model routing by logical role — `STRATEGY/WORKER/FAST/JUDGE/EMBEDDING` (§H, ADR-0005).
4. Safety spine — action classification, approval, verification, rollback, guardrails.
5. Closed learning loop — proper experiment methodology; no causal claims from before/after.
6. Website content is untrusted data, never instructions (§W).
7. Tenant isolation at two layers — app RBAC/ABAC + Postgres RLS `FORCE` (§F.2, ADR-0006 sibling).

## Components
| Layer | Package | Runtime |
|---|---|---|
| REST surface | `apps/api` | FastAPI, `/v1`, tenant middleware |
| Unit jobs | `apps/worker` | Celery + Redis (§AA) |
| Long loop | (Phase 11) | Temporal |
| Deterministic SEO | `packages/seo_core` | library |
| Model access | `packages/llm` | provider abstraction + router + cost meter |
| World access | `packages/tools` | tool registry — only path agents touch the world |
| Graph | `packages/knowledge_graph` | Postgres CTE + pgvector + tsvector |
| Safety spine | `packages/{planner,execution,verification,rollback}` | |
| Events | `packages/events` | transactional outbox → bus (ADR-0007) |
| Cross-cutting | `packages/common` | settings, logging, redaction, db session |

## Data stores
- **Postgres** (Neon prod / Docker dev): structured rows, graph, evidence metadata, vectors.
- **Object storage** (R2/S3 prod / MinIO dev): raw HTML, DOM, screenshots, SERP/AI payloads —
  content-addressed, immutable, lifecycle-managed (§F.4).
- **Redis**: Celery broker, rate-limit buckets, response cache.

## Request → tenant session
JWT (Supabase HS256 or local) → `Principal{user_id, tenant_id, roles}` → `get_db` opens a
Postgres session as `seo_app` (NOBYPASSRLS) → `SET LOCAL app.tenant_id` (+ `app.project_id`) →
RLS enforces isolation. Worker jobs use the identical `tenant_session()` from the job payload.
Dev shortcut: `X-Dev-Tenant`/`X-Dev-User` headers when `ENV=dev`.

## Status
Functional cores of Phases 0–13 built (11 migrations, ~140 tests, all green). The pipeline runs
end-to-end offline: crawl → technical/content/graph → issues → opportunities → structured plan →
approval → **execution against a real git repo** → verification → rollback-on-fail; plus
analytics/anomaly/experiments/learning, GEO citation tracking, an event-driven autonomous loop
(`agent_runs` + outbox relay + idempotent consumers + DLQ), a read API + Markdown reports, and
consolidated eval scorecards. Remaining work is integration gated on external keys/infra — see
`BUILD-LOG.md` "Honest status" and `../NEEDED-KEYS.md`.
