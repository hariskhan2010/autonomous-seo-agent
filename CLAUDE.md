# autonomous-seo-agent — repo guide for Claude Code

Build bible: `../A-TO-Z-PLAN.md`. Vision: `../Plan.md — Autonomous SEO Agent.md`.

## Rules
- Python via **uv** (`uv sync`, `uv run ...`). Target 3.13. Never edit `.venv` directly.
- `packages/` and `apps/*` are on pythonpath — import flat: `from seo_core...`, `from common...`, `from app...`.
- Deterministic SEO logic goes in `packages/seo_core` as pure functions (input dict -> output dict + evidence refs). No argparse, no file writing.
- Every finding must cite >=1 `evidence` row (ADR-0006). LLM output that drives execution is schema-validated.
- Model access ONLY through `packages/llm` by logical role (STRATEGY/WORKER/FAST/JUDGE/EMBEDDING). Never hard-code model names (ADR-0005).
- World access ONLY through `packages/tools`. No raw shell/db/fs/network in agents.
- Secrets never in code/logs/prompts — `packages/common/redaction.py` + its test.
- Tests: `uv run pytest`. Never let the suite go red. Add eval golden data per phase (`docs/EVALUATION.md`).

## Current phase
Deterministic + offline-testable core of Phases 0–12 built & green (13 migrations on Neon,
~200 tests), **plus a second pass that closed every code gap not strictly blocked on a live
credential**: LLM judge + revision loop (Phase 5), Core Web Vitals (Phase 3), the hosted GitHub-PR
adapter (Phase 8), real GSC/GA4 API calls (Phase 9), GEO prompt library + AI-Overview citations +
machine-readability (Phase 10), a widened autonomous allow-list, and the durable orchestrator —
`apps/worker/worker/temporal.SeoAgentWorkflow` (Phase 11, ADR-0003) — tested against Temporal's
real time-skipping test server (`tests/unit/test_temporal_workflow.py`), not a mock.

**2026-09-13 — closed two more gaps that were previously credential/infra-blocked:**
- **Google OAuth + per-project encrypted credential storage** (was explicitly "not yet designed").
  `db.models.credential.OAuthCredential` (RLS-enabled, migration 0013) + `packages/common/crypto.py`
  (Fernet, keyed from `ENCRYPTION_KEY`) + `integrations/oauth/google.py` (real token
  exchange/refresh/revoke against Google's endpoints, signed-state CSRF defense for the
  no-bearer-token callback route) + `apps/api/app/routers/oauth.py` (start/callback/status/revoke/
  config). `worker.jobs.analytics.ingest` now resolves a project's stored refresh token
  automatically when the caller doesn't pass one — closing the exact gap
  `get_metrics_provider`'s own docstring used to flag. Connecting is always a new row (never a
  mutable flag flip) — reconnect-after-revoke leaves a full audit trail, mirroring the sibling
  trading-agent project's `LiveTradingEnablement` pattern. Found and fixed in passing: three
  secret-shaped `Settings` fields (`pagespeed_api_key`, `crux_api_key`,
  `google_oauth_client_secret`) were missing from `secret_field_names` and so never got redacted —
  the exact bug class `test_settings_secrets.py` exists to catch, in the direction it didn't
  guard. All monkeypatched/fake-provider tests — no real Google credentials anywhere in the suite.
- **Playwright Tier-2 crawler** (`seo_core.crawl.render`) — same `FetchResult` shape as Tier 1, so
  `worker.jobs.crawl` dispatches on `CrawlOptions.tier` with no downstream branching. The hard
  part: a real browser independently resolves DNS and fetches every subresource itself, so
  Tier 1's SSRF guard (`crawl/safety.py`) only protects the top-level URL unless re-applied
  per-request — `page.route("**/*", ...)` intercepts literally everything Chromium tries to fetch
  and re-runs the identical guard before allowing it through. Proven two ways: the guard logic
  itself needs no real browser (`tests/unit/test_render_guard.py`, fake Route/Request doubles);
  Chromium actually launching and rendering in this environment is proven separately
  (`tests/integration/test_render_smoke.py`, skips cleanly if no browser binary is present).
  Runs in its own container (`infra/Dockerfile.playwright`, Playwright's own base image) — never
  bundled into the api/worker image, which has no browser and shouldn't need one. A dedicated
  Celery task (`crawl.run_tier2`) routes to a `render` queue (`worker/app.py`) that only the new
  `worker-render` compose service consumes, so a Tier-2 job can never land on a browser-less
  container.

**Phase 13 hardening pass (2026-09-13):**
- **Kill switch added**: a `Project`'s `approval_mode` could previously only ever be set once, at
  creation — no endpoint existed to change it afterward. `PATCH /v1/projects/{id}` (admin role,
  narrow to `approval_mode`, logged at `warning`) is now the real operational lever.
- **A real concurrency bug found and fixed, not just load-tested**: two experiments sharing an
  `opportunity_type` could conclude around the same time on two different workers and silently
  lose one's weight nudge — `worker.jobs.analytics.evaluate`'s `OpportunityWeight` read had no row
  lock. Fixed with `.with_for_update()`; proven with two real threads racing on the same row
  against Neon (`test_concurrent_evaluations_sharing_an_opportunity_type_dont_lose_an_update`).
- **Secret scanning was entirely missing** despite `SECURITY.md`-equivalent claims — added
  `detect-secrets` + `.secrets.baseline` (12 reviewed false positives: dev-default DB credentials,
  migration-file hashes, a deliberate test fixture) as a blocking CI step.
- `pip-audit` was previously advisory-only (`|| true`, explicitly flagged in the CI file's own
  comment as "until Phase 13 hardening") — now blocking; currently clean.
- `make type` was silently narrower than CI's own `mypy` invocation (missing `integrations` — so
  `apps/api/app/routers/oauth.py` and the whole `integrations/oauth` package were never actually
  checked by a dev running it locally); fixed.
- **`SECURITY.md`** and **`RUNBOOK.md`** — first-time setup, the Google OAuth connect flow, the
  approval-model table, the kill-switch procedure, rollback guidance, and an incident checklist.

**The dashboard (2026-09-13)**: built at `apps/dashboard` — Next.js 16, App Router, Server
Components calling the API server-side (dev-header identity never reaches the browser bundle).
Projects list/create, project overview with the approval-mode kill switch, opportunities board
with priority/status filtering, opportunity detail with the evidence viewer, plan detail with a
real approve/reject flow, changes list, issues list. Verified end-to-end against a real seeded
project through the real API (not just a clean build) — created a project, viewed an opportunity,
approved its plan, watched the UI correctly reflect the new state and hide the decision form.
Found and fixed two real backend gaps while building it:
- None of the list endpoints (`opportunities`, `issues`, `changes`, `crawls`, `anomalies`,
  `experiments`) were actually scoped to one project — for any tenant running more than one
  project they mixed every project's data together. Added the `project_id` query-param filter
  (matching `websites.py`'s existing convention) to all six, with a test proving two projects
  under one tenant are now genuinely isolated.
- `GET /opportunities/{id}/plans` didn't exist — no way to navigate from an opportunity to its
  plan without already knowing the plan_id. Added it.

**Real LLM keys wired up (2026-09-13)**: `config/model_registry.yaml` originally pointed every
role at `anthropic`/`openai` — but no provider adapters for those existed beyond
`anthropic_provider.py`, and the free-tier strategy `NEEDED-KEYS.md` itself recommends (Gemini +
OpenRouter + Zhipu) had no matching adapters at all. Built `gemini_provider.py`,
`openrouter_provider.py`, `zhipu_provider.py` (real httpx calls, unit-tested against fake
responses), registered them in `router.py`, repointed the registry (`STRATEGY`/`WORKER` → Gemini,
`FAST` → Zhipu, `JUDGE` → OpenRouter's `nvidia/nemotron-3-super-120b-a12b:free` — a genuinely
different model family from Gemini, not just a different routing label), and verified all four
roles end-to-end with real network calls using the real keys now in `.env`. Found in passing:
`glm-4-flash` (what the docs referenced) 404s against the current Zhipu API — `glm-4.5-flash` is
the live free-tier model.

**SerpAPI key set + verified (2026-09-17).** **Celery beat, cursor pagination +
`Idempotency-Key` (2026-09-28)** — see docs/BUILD-LOG.md; beat needs `BEAT_TARGETS` in `.env`.

**Remaining is genuinely credential/infra-gated** (TOMORROW.md + docs/BUILD-LOG.md "Honest
status"): `PAGESPEED_API_KEY` + `CRUX_API_KEY` (same GCP project as the OAuth client, already
created), a repo token for the Git-PR adapter, and a running Temporal server — locally the
`temporalio/auto-setup` container crashes on startup (not yet root-caused, see TOMORROW.md) — or
Temporal Cloud.

**Secrets baseline**: CI diffs `.secrets.baseline` against a Linux rescan, so it must use POSIX
paths. If you regenerate it on Windows, convert `\\` → `/` in every filename before committing.

## API auth (dev)
No Supabase needed locally: send headers `X-Dev-Tenant`, `X-Dev-User` (uuids), optional
`X-Dev-Role` (owner/admin/operator/viewer). Only honored when `ENV=dev`.

## DB
Neon project `hidden-cherry-91348040`. Runtime role `seo_app` (NOBYPASSRLS) via `.env` DATABASE_URL;
migrations via `neondb_owner` (DATABASE_URL_MIGRATOR). Use the Neon MCP for schema inspection/tuning.
`uv run alembic -c database/alembic.ini upgrade head`.
