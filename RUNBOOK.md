# Launch runbook

Operational reference for standing this system up and for an on-call operator responding to an
incident. See `A-TO-Z-PLAN.md` for design rationale, `CLAUDE.md` for build-phase status,
`SECURITY.md` for the security posture and disclosure process, `NEEDED-KEYS.md` for which real
credentials are still required before a given feature can actually run (not just be built).

## 1. First-time environment setup

```
make up             # Postgres 16 + Redis + MinIO (infra/docker-compose.yml)
uv sync
cp .env.example .env  # fill in provider/LLM/Google OAuth keys — never commit .env
make migrate         # applies every migration in database/migrations/versions/
make up-temporal      # adds the Temporal server + UI, if using the durable autonomous loop
```

Verify before doing anything else:
- `uv run pytest` is green against this environment (this project targets Neon in practice —
  expect real network latency per test versus a local Postgres; a full run can take several
  minutes).
- `psql` in as the `seo_app` role (not the migrator superuser) and confirm RLS is `FORCE`d on
  every application table — `tests/integration/test_rls_coverage.py` checks this automatically,
  but it's worth a manual look in a fresh environment.

## 2. Starting the system

```
make api                                            # FastAPI app (dev only — a real ASGI server in prod)
make worker                                          # Celery worker: crawl (Tier 1), content, keywords,
                                                      # analytics, geo, opportunities, planning, ...
make temporal-worker                                  # Temporal worker hosting SeoAgentWorkflow
docker compose -f infra/docker-compose.yml up worker-render  # Tier-2 (Playwright) — separate image,
                                                      # only needed if any project's crawls use tier="browser"
```

`worker-render` is optional: a project that only ever crawls with the default `tier="http"` never
needs it, and the default `worker` service is built from an image that has no browser at all — a
Tier-2 job can only ever run on `worker-render` (`worker/app.py`'s `task_routes` sends
`crawl.run_tier2` to the `render` queue that only this service consumes).

## 3. Connecting a project's Google account (GSC/GA4)

```
GET  /v1/projects/{project_id}/oauth/google/start    -> {"authorization_url": "..."}
                                                       # send the user here; Google redirects back to
                                                       # GOOGLE_OAUTH_REDIRECT_URI on consent
GET  /v1/projects/{project_id}/oauth/google/status   -> {"connected": bool, "account_email": ...}
PATCH /v1/projects/{project_id}/oauth/google/config  -> {"ga4_property_id": "properties/123"}  # GA4 only
POST /v1/projects/{project_id}/oauth/google/revoke   -> disconnects (best-effort revoke at Google too)
```

**The user's browser must call `/start` itself** (a `fetch(..., {credentials: "include"})` to the
API origin, or a navigation there) and finish the Google consent in that same browser: `/start`
sets an HttpOnly nonce cookie that `/callback` requires (login-CSRF defense). If a server calls
`/start` on the user's behalf, the cookie never reaches the browser and the callback returns
"finish the connect flow in the same browser that started it".

Once connected, `metrics.ingest` (`worker.jobs.analytics.ingest`) resolves the stored, encrypted
refresh token automatically — no need to pass one explicitly unless testing against a
different/temporary connection. Reconnecting (running `/start` again) automatically revokes the
previous connection first; both rows persist for audit purposes.

## 4. The approval model — what requires a human

| Action class | Autonomous? |
|---|---|
| `READ_ONLY` | Always auto |
| `LOW_RISK_WRITE` | Auto only if `approval_mode="autonomous"` AND the opportunity type is on the project's allow-list AND the owning agent's eval is above threshold |
| `HIGH_RISK_WRITE` | Never autonomous — requires a recorded human approval |
| `IRREVERSIBLE_EXTERNAL_ACTION` | Never autonomous, full stop, regardless of approval |

Enforced independently in two places (`packages/execution/approval.py::resolve` +
`packages/events/guardrails.py::check`) — a bug in one is not the only thing standing between a
proposed change and it actually landing. `Project.approval_mode` defaults to `"read_only"` for
every new project; nothing executes until that's explicitly changed.

Additional guardrails that apply regardless of approval mode: a mass-change threshold (default 50
pages — exceeding it always needs human approval even in autonomous mode), a loop cap (25) on the
autonomous cycle, and duplicate-action-hash detection (the exact same change is never applied
twice).

## 5. Kill switch

Set a project's `approval_mode` to `"read_only"` — every action class is blocked from that point
on, including ones already mid-flight the next time they're evaluated:

```
curl -X PATCH https://<api>/v1/projects/{project_id} \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"approval_mode": "read_only"}'
```

(`PATCH /v1/projects/{id}` — added in the 2026-09-13 hardening pass; previously `approval_mode`
could only ever be set once, at project creation, with no way to change it afterward.)

If a `HIGH_RISK_WRITE`/`IRREVERSIBLE_EXTERNAL_ACTION` change already has a live PR or a published
edit in flight, closing/reverting it at the source (GitHub, the CMS) is still necessary — the kill
switch stops new actions, it does not undo one already applied.

## 6. Rollback

- **Bad deploy of application code**: redeploy the previous image — no migration involved, safe
  to roll back at will.
- **Bad migration**: every migration in this repo is checked to round-trip
  (`alembic downgrade -1` then `upgrade head`) before merge — `downgrade` is safe to run. Never
  `DROP` a table by hand instead of going through Alembic; RLS policies and grants are recreated
  by the migration, not by the table alone.
- **A bad autonomous content/code change**: this is exactly what the Git-PR adapter (Phase 8) +
  verification + auto-rollback design exists for — revert the PR/commit; the mass-change guard and
  loop cap exist specifically to bound how much damage one bad cycle can do before a human
  notices.

## 7. Incident checklist

1. Kill switch the project first (§5) — stop the bleeding before investigating.
2. Pull `audit_logs` / the relevant `OutboxEvent` rows for the incident window — every guardrail
   decision and agent action is meant to be logged, pass or block.
3. Check whether the approval-mode and guardrail gates were actually satisfied, or whether this is
   a guardrail bug (see `SECURITY.md`'s in-scope list) — if the latter, this is both an incident
   and a security report; follow `SECURITY.md`'s disclosure process in addition to the immediate
   fix.
4. For an SSRF-adjacent incident (the crawler reached somewhere it shouldn't have): check whether
   it came through Tier 1 or Tier 2 — Tier 2's per-request guard (`page.route()`) is the newer,
   less battle-tested code path; confirm `tests/unit/test_render_guard.py` still covers the
   specific request shape involved and extend it if not.

## 8. CI gates that must stay green before any deploy

`ruff check`, `mypy --strict` (`packages apps integrations`), `detect-secrets scan` against
`.secrets.baseline`, `pip-audit`, a full migration up→down→up→models-in-sync check, `pytest`, and
the eval scorecard smoke suite (`.github/workflows/ci.yml`). None of these are advisory — a red CI
run blocks the deploy.

## 9. Backup & restore (Neon branching)

Neon keeps history for the project (`hidden-cherry-91348040`); a restore is a **new branch**, never
an in-place overwrite, so the damaged `main` stays available for forensics.

1. Neon console → Branches → **Create branch** from `main`, either at the current head or at a
   point in time just before the incident (within the plan's history window). Or ask Claude to use
   the Neon MCP `create_branch` / `restore_snapshot`.
2. Verify the copy before pointing anything at it — same query as the drill below: alembic head,
   table count, `FORCE` RLS on every table, `seo_app`/`seo_readonly` still `NOBYPASSRLS`, and row
   counts for the tables that matter.
3. Cut over: point `DATABASE_URL` / `DATABASE_URL_MIGRATOR` at the new branch's endpoint (or make it
   the default branch), restart api/worker/beat/temporal-worker.
4. Stored OAuth refresh tokens are encrypted with `ENCRYPTION_KEY` — a restore is useless without
   the same key, so the key must be backed up separately from the database.

**Drill, 2026-09-29:** branch `restore-drill-2026-09-29` created from `main` head; queryable in
~10 s; alembic head `f6f34c89b75f`, 64 tables, 60 RLS policies (all 60 `FORCE`), row counts
(tenants 2, projects 2, oauth_credentials 2, outbox_events 20) and both runtime roles
`NOBYPASSRLS` — all identical to `main`. Not exercised: point-in-time (pre-head) restore, the
cut-over step, and decrypting a restored OAuth token.
