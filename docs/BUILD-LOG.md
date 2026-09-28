# Build log

One entry per phase as it lands. Milestone/DoD tables in `../A-TO-Z-PLAN.md` §S/§T.

## Phase 0 — Architecture & scaffolding — ✅ DONE (2026-09-06)

**Shipped**
- Monorepo skeleton (`apps/`, `packages/`, `integrations/`, `mcp/`, `database/`, `tests/`, `docs/`, `docs/adr/`).
- `packages/common`: settings (pydantic-settings), secret redaction + test, structlog JSON logging with redaction processor.
- `apps/api`: FastAPI, `/v1` prefix, correlation-id + request-id middleware, error envelope, `/v1/health`, OpenAPI at `/v1/openapi.json`.
- `apps/worker`: Celery app (acks_late, prefetch=1, reject_on_worker_lost).
- `database/`: Alembic scaffold (env.py uses migrator-role URL; no migrations yet).
- `infra/`: docker-compose (pgvector/pg16 + redis + minio + api + worker), Dockerfile.api, db-init (extensions + `seo_rw`/`seo_ro`/`seo_migrator` roles).
- `config/model_registry.yaml`: logical roles STRATEGY/WORKER/FAST/JUDGE/EMBEDDING.
- `tests/eval/`: progressive eval harness (loader + scorecard + PRF) + smoke test.
- ADR 0001–0007. Docs: ARCHITECTURE, DATABASE, TOOLS, SECURITY, AGENTS, API, EVALUATION, DEPLOYMENT.
- CI: ruff + mypy(strict) + `alembic upgrade head` + pytest on ephemeral pg/redis.

**Acceptance**
- `uv run ruff check .` — clean.
- `uv run mypy packages apps` — clean (strict, 29 files).
- `uv run pytest` — 9 passed.
- `docker compose config` — valid. (Live `up` not run locally — Docker daemon off; CI covers it.)
- `alembic heads/history` — loads config + env.py, empty (correct).

**Open**
- ADR-0004 (auth backend) still `proposed` — decide before Phase 1 auth work.
- No Neon project yet — Phase 1 migration work needs a real Postgres (local Docker or Neon dev branch).
- Not committed to git (awaiting go-ahead).

## Phase 1 — Foundation — ✅ DONE (2026-09-06)

**Acceptance (A-TO-Z-PLAN.md §Phase 1)**
- ✅ Create tenant → project → website via API; second tenant cannot read the first's rows —
  proven at both the DB layer (`tests/integration/test_rls_isolation.py`) and the HTTP layer
  (`tests/integration/test_api_crud.py::test_cross_tenant_project_is_invisible_over_http`).
- ✅ Worker/API share one tenant-session code path; a session with no tenant context is
  migrations/tests only.
- ✅ `seo_app` cannot bypass RLS (asserted in a test).
- ✅ `pytest` green (**32 passed**), migrations up→down→up clean, ruff + mypy(strict, 53 files) clean.

**Built**
- **Neon project** `autonomous-seo-agent` (hidden-cherry-91348040, us-east-2, PG18). Roles:
  `seo_app` / `seo_readonly` (both NOBYPASSRLS), `neondb_owner` = migrator. Extensions:
  pgcrypto, vector, pg_trgm. `.env` written (gitignored).
  - Confirmed hazard: `neondb_owner` has BYPASSRLS → runtime correctly uses `seo_app`.
- `packages/db`: Base + mixins (`UUIDPKMixin`/`TimestampMixin`/`TenantMixin`/`ProjectScopedMixin`),
  `session.tenant_session()` (opens as seo_app, `SET LOCAL app.tenant_id/project_id`), `rls.py`
  policy helper.
- **17 models** across identity/project/evidence/events/runtime/audit.
- **Migration 0001** (`f95c40f1a6d8`): 17 tables + extensions + composite indexes + RLS
  `ENABLE` + `FORCE` + tenant-isolation policies on 14 tables; `users`/`prompt_templates`/
  `agent_versions` are documented identity-global (no RLS). Applied to Neon; down/up round-trips.
- **Cross-tenant isolation test** (`tests/integration/test_rls_isolation.py`, 4 cases, green on
  Neon): tenant sees only its rows · cannot read another tenant by id · WITH CHECK blocks
  cross-tenant insert · runtime role is NOBYPASSRLS.
- `packages/seo_core`: ported `validation.py` + `confidence.py` (pure functions, no file IO) + tests.
- `packages/llm`: `Role` enum, `registry.py` (loads `config/model_registry.yaml`, enforces
  JUDGE≠WORKER family, fallback-chain resolver), `provider.py` (LLMProvider protocol + LLMResult),
  Anthropic adapter (lazy client, cost estimate), `router.complete()` with the **redaction gate**
  (assert_clean before every provider call) + fallback walk + structured logging.
- CI updated: provisions DB roles, runs migration up→down→up, mypy strict enforced.
- **28 tests green**, ruff clean, mypy strict clean (48 files).

**Also built this pass**
- `apps/api/app/auth.py`: JWT verification (Supabase HS256 via `SUPABASE_JWT_SECRET`, or local
  `JWT_SECRET`); `ENV=dev` header bypass (`X-Dev-User`/`X-Dev-Tenant`/`X-Dev-Role`) so the stack
  runs without Supabase.
- `apps/api/app/deps.py`: `get_principal`, `get_db` (per-request `tenant_session`), `require_role`
  (owner>admin>operator>viewer hierarchy, membership fallback), `require_project` (ABAC).
- `apps/api/app/routers/`: `projects` (list/create/get + get/put `/config` = project-memory seed),
  `websites` (list/create/get). First-write auto-materialises the `tenants` row.
- `llm.router`: `complete_structured()` (schema-validated, one repair retry then fail) +
  per-call input-token budget guard (`BudgetExceeded`).

**Deferred to Phase 2 (with reason)**
- Cost meter persistence → a `tool_calls` row: that table ships with the tool registry in Phase 2.
  Interim: `llm.router` already emits structured cost/token/latency logs per call.
- Per-run / per-tenant cost ceilings: need `agent_runs` (Phase 8/11). Per-call cap is live.
- OTel span export wiring (endpoint env is read; exporter hookup lands with the crawler traces).
- `v0.1.0-foundation` tag — on the user's go-ahead (repo still uncommitted).

## Phase 2 — Crawler system — 🚧 CORE DONE (2026-09-06)

**Built**
- `seo_core/crawl/safety.py` — **SSRF guard**: blocks loopback / link-local / RFC-1918 / ULA /
  CGNAT / multicast / reserved / cloud-metadata (AWS+GCP+Azure+Alibaba) IPs; re-validates every
  redirect hop; refuses https→http downgrade; scheme allow-list; `allowed_hosts` enforcement;
  IP pinned on the validated address. Injectable resolver → fully offline-tested.
- `seo_core/crawl/fetcher.py` — Tier 1 async httpx fetch: manual redirect following (each hop
  guarded), per-host rate limiter (robots Crawl-delay), 10 MB streamed body cap, content-type
  gate.
- `seo_core/crawl/parser.py` — deterministic HTML → title/meta/canonical/robots/headings/
  internal+external links (deduped)/images+alt/JSON-LD/hreflang/word count. No LLM (§V).
- `seo_core/crawl/fingerprint.py` — sha256 `content_hash` (exact dedupe) + 64-bit simhash
  (near-dup) + `changed()` (Hamming > 3 or new).
- `seo_core/crawl/sitemap.py` — Tier 4: robots parsing (longest-match Allow/Disallow, Crawl-delay,
  Sitemap:) + sitemap + sitemapindex.
- `packages/common/storage.py` — S3/MinIO client, `tenant/{tid}/project/{pid}/...` key prefix,
  gzip, content-addressed. Optional in dev (crawl still records the hash if storage is down).
- `packages/tools/` — **tool registry** (§I): typed descriptor (name/version/risk/schemas/
  allowed_agents/scope/permission), schema-validated in+out, HIGH_RISK/IRREVERSIBLE forced to
  `approval_required`, agent allow-list, project-scope guard, always-on `tool_calls` audit.
  Built-in `fetch_url` (READ_ONLY, project-scoped).
- **Migration 0002** — `crawl_runs`, `page_snapshots` (immutable, content-addressed, the evidence
  store), `crawl_results`, `tool_calls` (also the LLM cost meter — carries role/provider/model/
  tokens/cost). All RLS `ENABLE`+`FORCE`. Applied to Neon; models in sync.
- `apps/worker/worker/jobs/crawl.py` + `crawl.run` Celery task — discover (robots+sitemap) →
  fetch → parse → fingerprint → delta check → object storage → `page_snapshots` + `crawl_results`
  + `evidence` rows → `crawl.completed` **via the transactional outbox**.
- Eval: first crawler-accuracy golden fixture (`tests/eval/golden/fixture_site/page.html`) with
  a hand-checked parser assertion set.
- **71 tests green** (SSRF suite, parser accuracy, fingerprint, robots/sitemap, registry contract,
  crawl-job end-to-end on Neon incl. "unchanged page → no new snapshot").

**Deferred**
- Tier 2 (Playwright browser render) + Tier 3 (proxy rotation) — need Docker/browser image and a
  proxy provider key. Interfaces reserved; `page_snapshots.tier` + `rendered_key` already modelled.
- `mcp/crawler` + `mcp/browser` MCP servers — the tool registry + `fetch_url` is the substance;
  MCP wrappers are a thin layer added when agents come online (Phase 11).
- Live-network acceptance run against the JS-heavy `asiangemstone` collection page — needs Tier 2.
- MinIO object-storage round-trip test — needs the container up (`make up`).
- Wire the LLM cost meter (`llm.router` → a `tool_calls` row) now that the table exists — small
  follow-up.

## Phase 3 — Technical SEO engine — 🚧 CORE DONE (2026-09-06)

**Built** — all deterministic, no LLM (§V). Consumes `crawl_results` + `page_snapshots`.
- `seo_core/technical/catalog.py` — **33-check catalogue** (ported from
  `seo-agent/skills/technical-seo-checker` + `on-page-auditor`): code → category / severity /
  title / fix. Categories: indexability, on_page, urls, links, schema, hreflang, crawlability,
  duplicates.
- `seo_core/technical/engine.py` — `analyze(pages, site)`:
  - *page-level*: 4xx/5xx, noindex-on-indexable, canonical missing / not-self, redirect chains,
    soft-404, title missing/long/short, meta-desc missing, h1 missing/multiple, thin content,
    query-param / uppercase / over-long URLs, **faceted-nav** pattern, image missing alt,
    JSON-LD missing / no-`@type`, hreflang no-self-reference.
  - *site-level*: robots unreachable / no-sitemap, empty sitemap, sitemap↔crawl mismatch,
    canonical/hreflang → non-200, **broken internal links**, **orphan pages** (link-graph),
    duplicate `<title>`, near-duplicate content (identical simhash).
  - de-duped by `normalized_key`, severity-sorted.
- **Migration 0003** — `seo_issues` (`normalized_key` UNIQUE per project → idempotent
  re-analysis; `first_seen`/`last_seen`/`seen_count`/`status` incl. `regressed`). RLS `FORCE`.
- `apps/worker/worker/jobs/technical.py` + `technical.analyze` Celery task — runs the engine over
  a crawl run, **upserts** `seo_issues` (idempotent), links each to the snapshot `evidence` row
  that proves it (`evidence_links` subject_type='issue'), emits `seo.issue.detected` via the outbox.
- The crawl job now records `sitemap_urls` / `robots_reachable` / `robots_has_sitemap` in
  `crawl_runs.stats` so the technical engine has site context.
- **Eval** — `tests/unit/test_technical_engine.py`: 14-page fixture site with a hand-labelled
  issue ledger → **recall 1.0, precision ≥ 0.9** (meets the §Phase 3 bar of prec ≥ 0.9 / recall ≥
  0.85). Plus idempotent-key stability + severity-sort tests.
- Integration test on Neon: crawl fixtures → `technical.analyze` → issues written, evidence-linked,
  `seo.issue.detected` emitted, **re-run creates 0 new issues** (`seen_count` bumped to 2).

**Deferred**
- CWV / performance checks (PageSpeed + CrUX) — need the API keys; stub the integration then wire.
- JS rendered-vs-raw diff + mobile-render parity — need crawler Tier 2 (Playwright).
- Google Rich Results API validation — use `validator.schema.org` or a local JSON-LD validator.
- LLM-phrased `fix` text — the catalogue's static `fix` strings are fine for now; an LLM pass can
  tailor them per finding later (advisory only, never drives execution).

## Phase 4 — Keyword + SERP intelligence — 🚧 OFFLINE CORE DONE (2026-09-06)

**Built** — deterministic (§V); no provider key needed for the logic, only for live data.
- `seo_core/keywords/normalize.py` — NFKC + punctuation strip + light plural stemming (so
  "ring"/"rings" cluster together).
- `seo_core/keywords/intent.py` — **12-class multi-label** intent engine (informational,
  navigational, commercial, transactional, local, visual, video, news, question, comparison,
  how_to, definitional) with per-label confidence. Ported + expanded from
  `seo-agent/lib/clustering.py::classify_intent`.
- `seo_core/keywords/clustering.py` — token-Jaccard greedy cluster (volume-seeded, stable across
  runs), ported from `lib/clustering.py`.
- `seo_core/serp/features.py` — SERP intelligence: top domains, feature inventory, PAA/related
  questions, entity/topic mining from titles+snippets, own/competitor positions, **content-gap
  list** (topics the ranking pages cover that a given page doesn't).
- `integrations/serp/` — **provider abstraction**: `SerpProvider` protocol + `get_provider()`
  (SerpAPI → DataForSEO fallback order), `SerpApiProvider` + `DataForSeoProvider` adapters (lazy,
  map raw JSON → normalised `SerpPayload`), `FakeSerpProvider` (deterministic fixtures for tests).
- **Migration 0004** — `keywords`, `keyword_clusters`, `search_intents` (multi-label),
  `keyword_page_map`, `serp_runs`, `serp_results`, `serp_features`, `serp_entities`. All RLS `FORCE`.
- `apps/worker/worker/jobs/keywords.py` + `keywords.ingest` / `serp.analyze` Celery tasks —
  ingest classifies + clusters + persists; serp.analyze pulls via the provider, stores run +
  results + features + entities + a `serp_snapshot` `evidence` row, emits `keywords.ingested` /
  `serp.analyzed` via the outbox.
- **Eval** — intent golden ledger (10 hand-labelled keywords, precision ≥ 0.85, mixed-intent
  multi-label check), clustering-stability regression, SERP feature-analysis + content-gap tests.
- Integration on Neon: ingest → keywords/intents/clusters persisted + idempotent re-ingest;
  serp.analyze (fake provider) → run/results/features/entities/evidence + event.

**Deferred** — need SerpAPI or DataForSEO credentials
- Live keyword discovery (seed → related → long-tail), volume/difficulty (provider or
  model-estimated + flagged), cannibalization detection, competitor rankings per cluster.
- Embedding-based clustering for the ambiguous tail (needs pgvector + the EMBEDDING role) —
  the token-Jaccard baseline is the reproducible floor.
- `FAST`-model intent classifier for genuinely ambiguous keywords — rule engine is the floor.

## Phase 5 — Content intelligence — 🚧 OFFLINE CORE DONE (2026-09-06)
- `seo_core/content/`: `inventory.classify_content_type` (article/product/category/landing/home
  from URL + schema + DOM), `quality.score_article` (ported from `lib/scoring.py`, 0-100 +
  PASS/REVISE/FAIL), `signals` (thin/outdated/orphan flags + cannibalization groups),
  `brief.build_brief` (deterministic skeleton from SERP evidence), `judge.rule_judge`
  (deterministic rubric — the ground truth the LLM `JUDGE` is scored against; never sole arbiter).
- **Migration 0005** — `content_items`, `content_scores`, `topics`, `entities` (RLS `FORCE`).
- `content.analyze` job — inventory from a crawl → rule score + flags + cannibalization → outbox.
- 7 unit tests. **Deferred:** LLM judge + revision loop (needs `JUDGE` key), decay (needs GSC
  history), full-body scoring (needs snapshot fetch from object storage).

## Phase 6 — Knowledge graph — 🚧 CORE DONE (2026-09-06)
- **Migration 0006** — `kg_nodes` (tsvector GIN + trigram GIN on label), `kg_edges` (evidence-backed
  via `evidence_links`), `embeddings` (§Z — dedicated table, model+version+content_hash),
  `embedding_jobs`. RLS `FORCE`; `pg_trgm` enabled.
- `packages/knowledge_graph/`: `KnowledgeGraph` (idempotent node/edge upserts, `traverse` via
  **depth-capped recursive CTE + visited-set**, `search` = tsvector rank + trigram similarity fused,
  `orphan_pages`), `recommend` (internal-link recs in the SOURCE/TARGET/ANCHOR/… shape,
  `topical_coverage`).
- `graph.build` job — nodes+edges from crawl results / keywords / SERP / content, idempotent.
- Integration test on Neon: build → traverse → orphan detect → hybrid search → link recs.
- **Deferred:** pgvector semantic half (needs EMBEDDING role), embedding lifecycle jobs.

## Phase 7 — Opportunity engine — 🚧 CORE DONE (2026-09-06)
- **Migration 0007** — `opportunities` (`normalized_key` UNIQUE per project → idempotent;
  business/seo/confidence/feasibility/risk inputs + score + P0–P3 + `action_class`). RLS `FORCE`.
- `packages/opportunity_engine/`: `score.priority_score` (deterministic
  `biz×seo×conf×feas÷risk → P0–P3`, aligned to `lib/scoring.py`), `detect` (issue→opportunity
  recipe map with action classes, content cannibalization/thin detectors, stable idempotent keys).
- `opportunities.detect` job — reads open `seo_issues` + content flags → upserts opportunities
  (idempotent), **links each to the issue's evidence** (rejects any issue-derived opportunity with
  zero evidence — §Phase 7 acceptance), emits `opportunity.created`.
- 3 unit tests (formula/buckets, issue mapping + idempotent keys, content detectors).

## Phase 8 — Safety spine — 🚧 MODEL + PLANNER DONE (2026-09-06)
- **Migration 0008** — the full spine: `plans`, `plan_steps` (**structured** — objective/tool/
  inputs/preconditions/expected_output/action_class/permission/verification/rollback/depends_on/
  timeout/retry/idempotency_key), `approvals`, `changes` (`side_effect_key` UNIQUE, `pre_state_hash`
  conflict field, `rollback_strategy`), `change_versions`, `verifications`, `rollbacks`,
  `incidents`, **`agent_decisions`** (§Y reproducibility record). RLS `FORCE`.
- `packages/planner/`: `plan_for_opportunity` — deterministic recipe map (opportunity type →
  tool + action class + rollback strategy + verifier) producing a structured `PlanDraft`;
  autonomous only for the `LOW_RISK_WRITE` allow-list ∩ tenant policy; unknown types return
  `unresolved` for `STRATEGY`-role planning. 4 unit tests.
### Phase 8b — Execution + verification + rollback — ✅ DONE (2026-09-06)
- `packages/execution/`: `ChangeAdapter` protocol + **`LocalGitAdapter`** (real git repo on disk —
  same shape a hosted GitHub-PR adapter takes) + `NoOpAdapter`; `engine.apply_change`
  (**conflict detection** via plan-time vs live `pre_state_hash`, idempotent no-op when already in
  the desired state); `approval.resolve` (read_only/assisted/autonomous × action class).
- `packages/verification/`: `engine.verify_change` + concrete verifiers (canonical / metadata /
  internal-link / schema / redirect / noindex). Immediate technical only (§K.5).
- `packages/rollback/engine.execute_rollback` — per-strategy (native/version_restore/compensating/
  manual/none); `none`/`manual` never auto-roll-back.
- `packages/events/guardrails` — loop cap, duplicate-action, write-lease, mass-change threshold,
  action-class gate, autonomous-allow-list check. Blocks (raises), never proceeds silently.
- `apps/worker/worker/jobs/planning.py` — `plan.build` (opportunity → Plan + PlanStep rows +
  `agent_decision`) and `plan.execute` (approval → guardrail → conflict-checked apply →
  `change_version` → verify → fail⇒rollback⇒incident → outbox event).
- **Minimal approval/ops API** (`/v1/opportunities`, `/opportunities/{id}/evidence`, `/plans/{id}`,
  `/plans/{id}/approve`, `/changes`) — the §K.4 console as a JSON API; hard precondition for writes.
- **Integration test on Neon + a real git repo**: assisted flow stops at the approval gate,
  resumes on approval, **commits land in the repo**, verification passes, `agent_decision` +
  `change_version` + `change.executed` event recorded; autonomous allow-list skips approval;
  read-only mode blocks. 7 tests.
- **Deferred:** hosted GitHub-PR adapter (needs a repo token — `LocalGitAdapter` proves the flow),
  live-fetch verification path (injection point exists; wires to the crawler), a browser UI for
  the console (Phase 12).

## Phase 9 — Analytics + learning — 🚧 OFFLINE CORE DONE (2026-09-06)
- **Migration 0009** — `metric_snapshots`, `anomalies`, `experiments` (with methodology fields),
  `learnings`, `opportunity_weights` (the closed-loop weights), `memory_entries`. RLS `FORCE`.
- `seo_core/analytics/`: `anomaly.detect_anomalies` (seasonality-aware baseline — same-weekday
  trailing window — z-score + min-% gate, so noise inside the band isn't flagged);
  `experiments.evaluate_experiment` — **enforces methodology**: min measurement window per metric,
  difference-in-differences when a control arm exists, confounder accounting (Google core-update
  windows, tracking changes) → `inconclusive` on any confounder; **`causal_language_allowed` is
  False without a control arm**.
- `integrations/analytics/`: `MetricsProvider` protocol + `get_metrics_provider` (GSC/GA4 lazy
  skeletons) + `FakeMetricsProvider` (seasonal series with injectable drop).
- `apps/worker/worker/jobs/analytics.py` — `metrics.ingest` (idempotent), `anomaly.detect`
  (→ `anomalies` + investigation checklist + `traffic.anomaly.detected`), `experiment.evaluate`
  (→ verdict + `learnings` + **shifts `opportunity_weights`** for success/regression above
  confidence).
- 8 unit + 2 integration tests (anomaly detection on a simulated drop; controlled experiment →
  causal verdict + weight shift). **Deferred:** real GSC/GA4 (OAuth), server-log analyzer.

## Phase 10 — GEO / AI search — 🚧 OFFLINE CORE DONE (2026-09-06)
- **Migration 0010** — `ai_prompts` (versioned), `ai_prompt_runs` (full context: provider/model/
  model_version/prompt_version/locale/timestamp/parser+version), `ai_responses` (raw retained),
  `ai_citations`, `ai_visibility_scores`. RLS `FORCE`.
- `seo_core/geo/`: `citations.parse_citations` (brand mention + position, competitor mentions,
  cited URLs, own-URL-cited, coarse sentiment — deterministic floor); `visibility.visibility_score`
  (0–100 per cluster×provider, always provider-qualified).
- `integrations/ai_providers/`: `AiProvider` protocol + `get_ai_provider`; **one
  `OpenAiCompatibleProvider`** covers OpenRouter/Zhipu/OpenAI/Perplexity + a Gemini shim (lazy);
  `FakeAiProvider` (canned answers) for offline tests.
- `apps/worker/worker/jobs/geo.py` — `geo.battery`: prompt set × providers → raw response
  (`ai_response` evidence) + parsed citations + weekly `ai_visibility_scores` + outbox event.
- 3 unit tests. **Deferred:** provider keys, full prompt library (30–50/cluster), AI-Overview via
  SerpAPI, entity-consistency / machine-readability tracks.

## Phase 11 — Autonomous operation (event core) — 🚧 DONE (2026-09-06)
- **Migration 0011** — `dead_letter_events`, `schedules`, `agent_runs` (the §J loop state row).
- `packages/events/bus.py` — **transactional-outbox relay**: polls unpublished `outbox_events`,
  runs every registered consumer, records `processed_events` (dedupe → redelivery is a no-op),
  increments `attempts` + dead-letters after `MAX_ATTEMPTS`, marks `published_at` only when all
  consumers succeeded (or the event is dead).
- `apps/worker/worker/pipeline.py` — the autonomous pipeline as **idempotent consumers**:
  `crawl.completed` → technical+content+graph; `seo.issue.detected` → opportunities.detect;
  `opportunity.created` → plan.build for P0/P1 (stops at the approval gate under assisted mode).
- `events.relay` Celery task drives it (worker beat in prod).
- Integration test on Neon: relay delivers once + marks published + no re-delivery; failing
  consumer retries then dead-letters. 2 tests.
- `apps/worker/worker/jobs/scheduler.py` — `scheduler.tick`: reads due `schedules`, enqueues the
  task, bumps `next_run_at` by cadence. Time-based trigger only, no workflow state (§AA).
- `apps/worker/worker/jobs/orchestrator.py` — **minimal orchestrator loop** (`agent_runs`-backed):
  opens a run, drains the event bus over a few passes so chained events settle
  (`crawl.completed` → analyze → issues → opportunities → plan.build), records the state it reached,
  **stops at the approval gate**. State is a DB row → a crash mid-run resumes from `agent_runs.state`.
- **Integration test on Neon**: seed a crawl → `run_once` → `seo_issues` + `opportunities` +
  `plans` awaiting approval all produced unattended; `agent_run.state == awaiting_approval`.
  Scheduler test: due schedule fires + reschedules a week out.
- **Deferred:** Celery beat wiring for the scheduler tick. → **cleared 2026-09-28** (see
  "Beat wiring + API pagination/idempotency" below).

### Phase 11 deferral cleared — the Temporal durable workflow (2026-09-12)
`apps/worker/worker/temporal/`: `SeoAgentWorkflow` (ADR-0003) — the always-on OBSERVE→PLAN→
(auto-execute | wait-for-human)→LEARN loop, replacing the one-shot `orchestrator.run_once` for
real multi-day autonomous operation. `detect_and_plan` / `execute_approved_plan` activities wrap
the existing jobs (`orchestrator.run_once`, `planning.execute`) directly — no duplicated business
logic. Approval/rejection arrive as signals (`approve_plan`), not DB polling; `stop` ends the loop;
`status` query exposes pass count + pending decisions; `continue_as_new` resets history every
`max_passes_before_continue` passes so a long-lived loop doesn't grow unbounded. `run_worker.py`
is the Temporal worker entrypoint (`make temporal-worker`); `client.py` has thin
start/signal/query helpers for wiring into the approval API later.
**Tested for real** — 5 tests run the actual workflow against Temporal's own time-skipping test
server (`tests/unit/test_temporal_workflow.py`), not a mock: autonomous plans execute without
waiting, awaiting-approval plans only execute after an `approve_plan` signal, a `rejected`
decision never executes, `stop` ends the loop mid-run, and starting a duplicate workflow id
fails closed. `make up-temporal` self-hosts a dev Temporal server + UI via docker-compose (not
run against a live daemon in this pass — Docker wasn't available in-session; the compose file's
YAML is validated, the workflow logic is validated against the real SDK/test-server, but the
`docker compose up` path itself is not).
**Deferral cleared (2026-09-12):** `POST /v1/plans/{id}/approve` now best-effort signals a running
workflow via `worker.temporal.client.signal_approval`, registered as a FastAPI `BackgroundTasks`
callback so it only fires *after* the `Approval` row's transaction commits (signalling before that
would race a Temporal activity reading the row back). Not configured / no workflow running is a
silent no-op — the `Approval` row is always the source of truth regardless. 3 integration tests
(signals when configured, stays silent when not, approval still succeeds if the signal itself
fails). **Still needed:** Temporal Cloud credentials for prod; a real running server to point at
in dev (`make up-temporal`).

### Cross-cutting bug found + fixed while wiring the above: RLS project-scope cast (2026-09-12)
Every project-scoped table's RLS policy (`db.rls.enable`) had `current_setting('app.project_id',
true) = '' OR project_id = current_setting('app.project_id', true)::uuid` — PostgreSQL does not
guarantee left-to-right OR evaluation, so the planner could still attempt the `''::uuid` cast in
the second disjunct even when the first was true. Any **tenant-only** session (`tenant_session
(tenant_id)` with no `project_id` — most API routes, since a project_id isn't always in the URL:
`/v1/opportunities`, `/v1/plans/{id}`, `/v1/plans/{id}/approve`, …) crashed with `invalid input
syntax for type uuid: ""` the moment it touched a project-scoped table. Confirmed failing live
against Neon — this was the *first* test in the whole suite to exercise that exact path (API →
tenant-only session → project-scoped table), so it had never been caught.
Fix: `NULLIF(current_setting(...), '')` collapses `''` to `NULL` before the cast — `NULL::uuid`
never errors, so it's safe regardless of evaluation order (`db.rls.policy_predicate`). **Migration
0012** re-points all 45 existing project-scoped policies at the fixed predicate (no schema/data
change — `redefine()` drops + recreates each policy). Verified: reproduces the exact original
failure on downgrade, fixed again on re-upgrade (clean up→down→up round-trip), full suite green.

### Phase 1 deferral cleared — LLM cost meter
`packages/llm/meter.py` + `router.complete(tenant_id=…)` now persist every LLM call as a
`tool_calls` row (tool=`llm.<role>`, role/provider/model/tokens/cost). Best-effort — never breaks
a call.

### Phase 8 — autonomous allow-list widened (2026-09-12)
`packages/planner/build.py`'s `_AUTONOMOUS_ALLOWLIST` ceiling now also includes
`fix_technical_issue` and `add_internal_links` (previously only `fix_canonical`/`add_schema`) —
both `LOW_RISK_WRITE` with native rollback, the same safety profile as the original two. This
only raises the ceiling of what a tenant *can* opt into (`Project.config.autonomous_types`); it
does not enroll anyone automatically, and the `HIGH_RISK_WRITE`/`IRREVERSIBLE_EXTERNAL_ACTION`
boundary (never autonomous, enforced independently in both `execution.approval.resolve` and
`events.guardrails.check`) is unchanged.

## Phase 12 — Multi-tenant + API + dashboard — 🚧 PARTIAL (2026-09-06)
- **RLS-policy-coverage test** (`test_rls_coverage.py`): every one of ~58 app tables has
  `ENABLE` + `FORCE` ROW LEVEL SECURITY + a tenant-isolation policy (3 documented global config
  tables exempt). Fails CI if a new table is added without RLS. §Phase 12 acceptance gate.
- Approval/ops API (`/v1/opportunities`, `/opportunities/{id}/evidence`, `/plans/{id}`,
  `/plans/{id}/approve`, `/changes`).
- **Read API** (`apps/api/app/routers/data.py`): `/v1/crawls`, `/issues`, `/keywords`,
  `/anomalies`, `/experiments`, `/geo/visibility`, `/reports/executive` + `/reports/technical`
  (Markdown).
- **Reporting engine** (`packages/reporting/`): deterministic Markdown executive + technical
  reports (performance deltas, priority opportunities, recent changes, AI-visibility, issues by
  severity). 2 unit tests. PDF/email = a wrapper added with the mail provider.
- **Deferred:** ~~cursor pagination + `Idempotency-Key` on the new endpoints~~ (cleared
  2026-09-28, see below),
  per-tenant API keys + quotas, competitors/backlinks endpoints, the Next.js dashboard (evolve
  a fresh Next.js dashboard wired to this API), Slack/email digests.

## Phase 13 — Observability, evaluation, security, launch — 🚧 PARTIAL (2026-09-06)
- **Consolidated eval scorecards** (`tests/eval/scorecards.py` + `test_scorecards.py`): one runner
  over every engine's golden set → per-engine `ScorecardRow` (value/threshold/passed) with the
  auto-demote threshold table (§P). CI runs the smoke subset; nightly runs the full matrix.
- CI: added `pip-audit` dependency scan (advisory) + the eval-scorecard step; mypy now covers
  `integrations/` too.
- Observability foundation (structured JSON logs + secret redaction + correlation IDs + OTel
  tracing hooks) is in from Phase 1 and every job emits structured events.
- **Deferred:** OTel exporter wiring to a backend (needs an endpoint key), Grafana/dashboard
  panels, a dedicated `security-review` pass on the write path + crawler + auth, load test,
  backup/restore drill, `DEPLOYMENT.md` launch runbook.

## Beat wiring + API pagination/idempotency — ✅ DONE (2026-09-28, branch `cloud/improvements`)

Code-only pass — nothing here needs a live credential.

- **Celery beat (Phase 11 deferral).** `worker/beat.py` builds `celery_app.conf.beat_schedule`:
  one `scheduler.tick` + one `events.relay` entry per configured target. Targets are explicit
  config (`BEAT_TARGETS=tenant_uuid:project_uuid,...`), not discovered — the runtime role is
  NOBYPASSRLS and both tasks run inside `tenant_session`, so beat cannot (and must not) list every
  tenant's projects itself. Intervals: `BEAT_SCHEDULER_TICK_SECONDS` (default 60) /
  `BEAT_EVENTS_RELAY_SECONDS` (default 15), in `common.settings`. Each entry `expires` after its
  own interval so a backed-up broker drops stale ticks instead of piling them up (both tasks are
  idempotent). Malformed targets fail loudly at import. New `beat` compose service (profile
  `full`; run exactly one) and `make beat`. 9 unit tests incl. a fresh-interpreter check that
  env vars actually reach `celery_app.conf.beat_schedule`.
- **Cursor pagination (Phase 12 deferral).** `app/pagination.py` — keyset over
  `(sort_key DESC, id DESC)` with an opaque cursor scoped to the endpoint that minted it (a cursor
  from `/changes` is a 400 on `/issues`). Wired into `/crawls`, `/issues`, `/keywords`,
  `/anomalies`, `/experiments`, `/geo/visibility`, `/opportunities`, `/changes`. **Backward
  compatible**: bodies stay bare arrays (the dashboard is unaffected); the next cursor is in the
  `X-Next-Cursor` header + `Link: rel="next"`; omitting `limit`/`cursor` keeps the legacy full
  listing (`/crawls` keeps its existing default `limit=20`). `/keywords` already had an object
  body, so it gains a `next_cursor` field. `/issues` was previously unordered — it is now
  newest-first. (There is no separate issues router; `/issues` lives in `data.py`.)
- **`Idempotency-Key` (Phase 12 deferral).** The "helper" that existed was the `job_runs`
  idempotency ledger (`db.models.runtime.JobRun`, migration 0001) — there was no request-level
  function, so `app/idempotency.py` is a thin layer over that ledger, not a second store. The
  ledger row is written in the same transaction as the endpoint's writes: same key + same request
  → replay (same status, `Idempotent-Replayed: true`); same key + different request → 422; still
  in flight → 409; a failed request rolls back with its row, so errors are never cached. Ledger
  key = `api:` + sha256(tenant | scope | client key) — tenants/endpoints can't collide on the
  globally-unique column and the raw key is never stored. Wired on `POST /projects`,
  `POST /websites`, `POST /plans/{id}/approve` (a replayed approval neither writes a second
  `Approval` nor re-signals Temporal).
- Tests: 21 new unit tests (fake session, no DB) + 4 integration tests on real Postgres (keyset
  walk with tied scores covers every row exactly once; approve replay writes one `Approval`;
  failed request doesn't burn the key; cross-tenant key reuse is independent). Full suite run
  locally against a throwaway PostgreSQL 16 + pgvector with the CI role setup
  (`infra/db-init/01-init.sql`), migrations up → down → up → `alembic check` clean.
- Docs: `docs/API.md` conventions updated to what is actually implemented; this "Honest status"
  table rewritten (it still listed LLM keys, Google OAuth, Tier 2, the dashboard, SerpAPI and the
  git commit as open — all done, see `CLAUDE.md` / `TOMORROW.md`).

## Local Temporal + security review — ✅ DONE (2026-09-29, branch `cloud/improvements`)

**Local Temporal:** `temporalio/auto-setup:1.24.2` (deprecated upstream, crashed with exit 2) is
replaced by the Temporal CLI dev server (`server start-dev`, SQLite, UI on :8080); `temporal-ui`
dropped. `make up-temporal` (Docker) or `make temporal-dev` (no Docker, needs the CLI). The
`SeoAgentWorkflow` suite passes against a real dev server (`WorkflowEnvironment.start_local()`);
the Docker image path itself is not yet run.

**Security review (auth + write path)** — fixed, with `tests/unit/test_security_hardening.py`:
- *Critical — fail-open config.* `env` defaulted to `dev` (enabling the `X-Dev-*` header bypass)
  and `JWT_SECRET`/`APP_SECRET_KEY`/`WEBHOOK_SIGNING_SECRET`/`ENCRYPTION_KEY` defaulted to a public
  placeholder, unchecked: a prod deploy missing any of them let anyone mint a JWT for any tenant, or
  decrypt stored OAuth refresh tokens. Now `Settings` refuses to start outside dev/test unless all
  four are real (>= 32 chars), and `Dockerfile.api`/`Dockerfile.playwright` default to `ENV=prod`
  (compose still sets `ENV=dev` via `.env`).
- *High — path traversal in execution adapters.* `LocalGitAdapter` joined `ChangeSpec.path`
  unchecked (`../`, absolute paths, `.git/hooks/*` -> code execution via `post-commit`);
  `GitHubPRAdapter` built API URLs from it. `safe_repo_path()` now rejects `..`, absolute/drive
  paths, `.git/`, `.github/workflows/`; the local adapter also re-checks the resolved path stays in
  the repo, before any git call.
- *Medium — bearer tokens.* `exp` + `sub` now required (a token without `exp` never expired);
  JWTs carrying a `purpose` claim (the OAuth `state`, same signing key) are refused as API tokens;
  malformed `X-Dev-*` headers are a 400, not a 500.

- *Medium — OAuth login-CSRF (fixed same day).* The Google OAuth `state` was signed and bound to
  tenant/project/user but not to the browser, so an attacker could start a connect flow for their
  own project and get a victim to consent, storing the victim's GSC/GA4 access in the attacker's
  project. `/start` now sets a random nonce as an HttpOnly, callback-path-scoped, SameSite=Lax
  cookie (Secure outside dev) and `state` carries only its SHA-256; `/callback` refuses unless the
  cookie matches, before redeeming Google's code, then clears it (also closes same-browser replay).
  **Contract change:** the browser itself must call `/start` (`fetch(..., {credentials:
  "include"})` or a navigation to the API origin) — a server-side call drops the cookie.

**Not covered:**
- Crawler (SSRF guard, Tier-2 per-request re-check) was not re-reviewed in this pass — it relies
  on its existing test suites (`test_ssrf*`, `test_render_guard.py`). Still worth a dedicated look.

---

## Honest status — what "complete" means here

**Built and green:** the deterministic + offline-testable core of Phases 0–13 (monorepo + CI, DB
spine with RLS `FORCE` tenant isolation + a coverage gate, evidence/provenance, outbox + relay +
DLQ, model roles + router + redaction, tool registry, SSRF-guarded Tier-1 **and Tier-2
(Playwright)** crawler, technical/keyword/content/graph/opportunity engines, the full
plan → approve → execute → verify → rollback safety spine, analytics + experiments + learning
loop, GEO, the event-driven pipeline **now on a Celery beat timer**, read API with cursor
pagination + `Idempotency-Key`, reporting, eval scorecards, the Temporal `SeoAgentWorkflow`
tested against Temporal's test server), **13 migrations**. Also done and verified with real
calls since this table was first written: LLM provider keys for all roles (Gemini / OpenRouter /
Zhipu), Google OAuth + per-project encrypted token storage, SerpAPI, the Next.js dashboard, and
the whole repo committed to git.

**Still open — each needs something outside the code:**
| Area | Status / blocker |
|---|---|
| Core Web Vitals running live (code done) | `PAGESPEED_API_KEY` + `CRUX_API_KEY` (same GCP project as the OAuth client) — `TOMORROW.md` §1 |
| Hosted GitHub-PR execution adapter running live (code done) | a fine-grained `GITHUB_TOKEN` (Contents + Pull requests: read/write) — `TOMORROW.md` §2 |
| Durable Temporal workflow running in prod (passes against a real local dev server) | Temporal Cloud credentials; locally `make up-temporal` / `make temporal-dev` (Docker path not yet run) |
| Crawler Tier 3 (proxy rotation for bot-protected sites) | not built; needs a proxy provider (`PROXY_URL`/credentials) |
| OTel export + dashboards | exporter hookup + Grafana panels need an OTLP backend endpoint/key |
| Load test | not run |
| Backup / restore drill | not run (Neon branch restore is the likely mechanism) |
| Crawler SSRF / Tier-2 guard re-review | not re-reviewed in the 2026-09-29 security pass |

The architecture, schema, engines and the full safety/execution loop are in place and tested;
what remains is live-credential/infra integration and the Phase 13 launch-readiness work above.
