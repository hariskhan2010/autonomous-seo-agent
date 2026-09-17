# Needed keys & accounts

Fill these into `.env` (copy from `.env.example`). `[ ]` = not done yet.
Full reference + cost table: `../A-TO-Z-PLAN.md` §V.1. Provider strategy: **free tiers now, premium
subscriptions once the system works.**

Legend — **F** = free / free-tier · **P** = paid (pay-as-you-go) · **$$** = expensive, can defer.

---

## ✅ Already set (dev)

- `DATABASE_URL`, `DATABASE_URL_MIGRATOR` — Neon project `hidden-cherry-91348040`
- `REDIS_URL` — local (needs `make up` / Docker running)
- `JWT_SECRET`, `APP_SECRET_KEY`, `WEBHOOK_SIGNING_SECRET`, `ENCRYPTION_KEY` — generated
- `S3_*` — MinIO defaults (needs `make up`)

---

## 🔴 NEED NOW — Phase 1–3 (LLM + core grounding)

| [ ] | Env var(s) | Service | Tier | Where to get / notes |
|---|---|---|---|---|
| [x] | `GEMINI_API_KEY` | Google Gemini API | F | aistudio.google.com → "Get API key". Big free quota. Powers `STRATEGY` + `WORKER` roles — verified with a real completion call (2026-09-13). |
| [x] | `OPENROUTER_API_KEY` | OpenRouter | F/P | openrouter.ai → Keys. One key = many models. Powers `JUDGE` — `nvidia/nemotron-3-super-120b-a12b:free`, a genuinely different model family from `WORKER` (Gemini), not just a different route. Verified with a real call. |
| [x] | `ZHIPU_API_KEY` | Zhipu / GLM | F | open.bigmodel.cn (or z.ai) → API keys. Powers `FAST`. **`glm-4-flash` 404s against the current API — use `glm-4.5-flash`** (found and fixed in `config/model_registry.yaml` while wiring up a real key). Verified with a real call. |
| [x] | `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | Google Cloud OAuth client | F | console.cloud.google.com → new project → APIs & Services → Credentials → OAuth client (Web). Also used for user login. One project, enable the APIs below in it. **Must also add your `GOOGLE_OAUTH_REDIRECT_URI` value (default `http://localhost:8000/v1/oauth/google/callback`, or your real API host in prod) to the client's "Authorized redirect URIs" list** — Google rejects the callback with `redirect_uri_mismatch` otherwise. The connect flow (`apps/api/app/routers/oauth.py`) requests `webmasters.readonly` + `analytics.readonly` scopes; nothing extra to enable for those beyond the two APIs below. |
| [ ] | `PAGESPEED_API_KEY` | PageSpeed Insights API | F | Same GCP project → enable "PageSpeed Insights API" → create an API key. Phase 3 (Core Web Vitals). |
| [ ] | `CRUX_API_KEY` | Chrome UX Report API | F | Same GCP project → enable "Chrome UX Report API" → API key. Phase 3 (field CWV). |

**2026-09-13 — a real gap closed alongside these keys**: `config/model_registry.yaml` originally
pointed every role at `anthropic`/`openai`, but no adapters for those free-tier providers existed
in `packages/llm/providers/` at all — the registry couldn't actually run with the keys this table
tells you to get first. Built `gemini_provider.py`, `openrouter_provider.py`, `zhipu_provider.py`
(real httpx calls, unit-tested against fake responses, then verified end-to-end with real keys for
all four roles), registered them in `router.py`, and repointed the registry: `STRATEGY`/`WORKER` →
Gemini, `FAST` → Zhipu, `JUDGE` → OpenRouter (family-diversity requirement satisfied by both the
provider *and* the underlying model, not just the routing label). Anthropic/OpenAI bindings still
work (`anthropic_provider.py` untouched) — switching back is a `model_registry.yaml` edit, not a
code change, once/if you're on a paid tier.

**Embeddings:** no key needed — `EMBEDDING` role runs a local model (`bge-small`, free). Add
`VOYAGE_API_KEY` or `OPENAI_API_KEY` later only if you want higher-quality vectors.

**Auth backend (`ADR-0004` = Supabase):** for local dev the `X-Dev-Tenant` / `X-Dev-User`
headers work with no Supabase. Set these when you want real login:
| [ ] | `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_KEY` / `SUPABASE_JWT_SECRET` | Supabase | F | supabase.com → project → Settings → API. `SUPABASE_JWT_SECRET` is under Settings → API → JWT Settings. |

---

## 🟡 NEED SOON — Phase 2 (Tier 2/3) + Phase 4 (keywords/SERP)

| [ ] | Env var(s) | Service | Tier | Where to get / notes |
|---|---|---|---|---|
| [ ] | `SERPAPI_API_KEY` | SerpAPI | P | serpapi.com. ~$75/mo entry. Primary SERP source (never scrape Google directly). |
| [ ] | `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD` | DataForSEO | P | dataforseo.com. Pay-as-you-go (~$25 to start). Cheaper at volume; SerpAPI fallback. Start with just this if budget is tight. |
| [ ] | `PROXY_URL` / `PROXY_USERNAME` / `PROXY_PASSWORD` | Proxy provider | P | Bright Data / Oxylabs / ScraperAPI. Only needed for crawler **Tier 3** (bot-protected sites). Pay-as-you-go ~$10–50/mo. Skip until a target site blocks Tier 1. |

---

## 🟢 NEED LATER — Phase 8+ (execution, analytics, GEO, launch)

| [ ] | Env var(s) | Service | Tier | Phase | Notes |
|---|---|---|---|---|---|
| [ ] | `OPENAI_API_KEY` | OpenAI | P | 5 | Alt `JUDGE` family + a GEO provider. OpenRouter can substitute for now. |
| [ ] | `PERPLEXITY_API_KEY` | Perplexity | P | 10 | GEO — AI-answer citations. `sonar` models are cheap. |
| [ ] | `AHREFS_API_KEY` *or* `SEMRUSH_API_KEY` *or* `MOZ_ACCESS_ID`+`MOZ_SECRET` | Backlink data | $$ | 7 | Ahrefs/Semrush APIs are pricey; Moz Links API is the cheap entry. Deferrable — Phase 7 can stub backlinks. |
| [ ] | (uses Google OAuth) | Search Console API | F | 1/9 | Enable "Google Search Console API" in the GCP project. Covers URL Inspection (indexation). |
| [ ] | (uses Google OAuth) | Google Analytics Data API (GA4) | F | 9 | Enable "Google Analytics Data API". Property must be GA4. |
| [ ] | `VERCEL_TOKEN` | Vercel API | F | 9 | vercel.com/account/tokens (read-only). Deployment history for anomaly investigation. |
| [ ] | `GITHUB_APP_ID` + `GITHUB_APP_PRIVATE_KEY` *or* `GITHUB_TOKEN` | GitHub | F | 8 | Git-PR execution adapter. Fine-grained token / App scoped to the target repo. |
| [ ] | `TEMPORAL_ADDRESS` / `TEMPORAL_NAMESPACE` / `TEMPORAL_API_KEY` | Temporal | F/P | 11 | The durable autonomous-loop workflow (`worker.temporal`) is built and tested against Temporal's own time-skipping test server — just needs a real server to point at. `make up-temporal` self-hosts one (docker-compose); then `TEMPORAL_ADDRESS=localhost:7233` for a host-run worker, or leave unset and use `make temporal-worker` inside the compose network (`temporal:7233`, already wired). Temporal Cloud (`TEMPORAL_NAMESPACE` + `TEMPORAL_API_KEY`) for prod. |
| [ ] | `SENTRY_DSN` | Sentry | F | 1+ | sentry.io free tier. Error tracking. |
| [ ] | `OTEL_EXPORTER_OTLP_ENDPOINT` / `OTEL_EXPORTER_OTLP_HEADERS` | Axiom / Grafana Cloud / Honeycomb | F | 1+ | OTLP trace ingest. All have free tiers. |
| [ ] | `RESEND_API_KEY` | Resend (or Postmark/SendGrid) | F/P | 12 | Reports, digests, approval emails. Free = 3k/mo. Needs a verified sending domain. |
| [ ] | `SLACK_BOT_TOKEN` / `SLACK_SIGNING_SECRET` | Slack app | F | 12 | api.slack.com/apps. Anomaly / approval / verification-failure alerts. |
| [ ] | `SECRET_MANAGER_URL` | Infisical / Doppler / AWS Secrets Manager | F/P | 12 | Prod secret storage + per-tenant integration creds. Dev uses `.env`. |
| [ ] | Rich Results / schema validation | — | F | 3 | No official API. Uses `validator.schema.org` or a local JSON-LD validator. No key. |

**Per-client CMS** (only when you onboard a non-Git site): `WP_APP_PASSWORD`,
`SHOPIFY_ADMIN_TOKEN`, etc.

---

## Minimum to keep building right now

Just these three unblock Phases 1–3:

```
GEMINI_API_KEY=
OPENROUTER_API_KEY=
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
```

Plus `make up` (Docker) for local Postgres/Redis/MinIO. Everything else can wait for its phase.
