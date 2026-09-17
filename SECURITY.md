# Security

## Reporting a vulnerability

Open a private GitHub Security Advisory on this repository (Security tab → "Report a
vulnerability"), or open an issue tagged `security` with only a description of the class of
problem — never a working exploit or credentials — if advisories aren't available. Do not open a
public issue containing a live API key, database credential, OAuth refresh token, or an exploit
against a running tenant.

## What's in scope

- Anything that could leak an LLM/data-provider API key or a stored Google OAuth refresh token
  (via logs, prompts, error messages, or an API response).
- Any path that could apply a `HIGH_RISK_WRITE` or `IRREVERSIBLE_EXTERNAL_ACTION` change (a live
  PR merge, a published content change) without a real human approval (`packages/execution/
  approval.py`, `packages/events/guardrails.py`) — this is the single most important invariant in
  the system, enforced independently in both places (defense in depth, not a single point of
  failure).
- Tenant/project data isolation (RLS) bypass.
- SSRF: any path that lets the crawler (Tier 1 `httpx` or Tier 2 Playwright) reach a loopback,
  link-local, private, or cloud-metadata address. Tier 2 is the harder case — a real browser
  independently resolves DNS and fetches every subresource itself, so the guard has to be
  re-applied per-request (`seo_core/crawl/render.py`'s `page.route()` interception), not just to
  the top-level URL.
- Anything that could disable or bypass the mass-change guard, loop cap, or duplicate-action
  detection in `packages/events/guardrails.py`.

## Design commitments

- Secrets never enter an LLM prompt or a log line (`packages/common/redaction.py`, gated before
  every outbound call). Every name in `Settings.secret_field_names` must correspond to a real
  declared field, checked in both directions by `tests/unit/test_settings_secrets.py` — a missing
  field silently never redacts, and (as of 2026-09-13) three genuinely secret fields
  (`pagespeed_api_key`, `crux_api_key`, `google_oauth_client_secret`) were found missing from that
  list and fixed.
- A connected Google OAuth account's refresh token is encrypted at rest
  (`packages/common/crypto.py`, Fernet keyed from `ENCRYPTION_KEY`) and never returned by any API
  response (`OAuthStatusOut` carries only `account_email`/timestamps). Connecting is always a new
  row, never a mutable flag flip — a revoke-then-reconnect cycle leaves a full audit trail.
- Every project-scoped RLS policy is `FORCE`d, so no application role — including a managed
  Postgres provider's owner role — is exempt (`packages/db/rls.py`); `tests/integration/
  test_rls_coverage.py` fails CI if a new table ships without it.
- The crawler's SSRF guard (`seo_core/crawl/safety.py`) resolves DNS itself and pins the
  connection to the validated IP, re-validating after every redirect hop — defeats
  DNS-rebinding/TOCTOU. Scheme allow-list is http/https only.
- `detect-secrets` and `pip-audit` run in CI (`.github/workflows/ci.yml`) against
  `.secrets.baseline` and the resolved dependency set, respectively — both blocking as of the
  2026-09-13 hardening pass (`pip-audit` was previously advisory-only, `|| true`).
- The LLM judge (Phase 5 content quality) is never the sole arbiter: every LLM verdict is
  cross-checked against a deterministic rule baseline, and a wild disagreement or a call failure
  falls back to the rule score rather than trusting the model blindly (`worker/jobs/content.py::
  llm_judge`).
- Read-only is the default approval mode for a new project (`Project.approval_mode="read_only"`,
  `apps/api/app/routers/projects.py`); autonomous mode is an explicit, per-project, per-change-type
  opt-in, never a default.
