# Security

Spec: `../A-TO-Z-PLAN.md` §N, §W, §F.2, §Phase 2, §Phase 13.

## Secrets
- Dev: `.env` (gitignored). Prod: secret manager. Never in code, frontend, or an LLM prompt.
- `packages/common/redaction.py` scrubs secrets from every log line and every outbound LLM
  request. `tests/unit/test_redaction.py` fails if a known token survives.
- Scoped, short-lived tokens; least privilege per integration; encrypted at rest.

## Tenant isolation (two layers)
1. **App**: RBAC roles (`owner/admin/operator/viewer`) + ABAC on `project_id` membership; every
   endpoint declares required role + scope.
2. **DB**: RLS on every table keyed to `app.tenant_id` / `app.project_id`, all `FORCE ROW LEVEL
   SECURITY`. Runtime roles `seo_rw` / `seo_ro` are NOSUPERUSER + NOBYPASSRLS. `seo_migrator`
   owns the schema and is used only by Alembic. A repo-level assertion helper re-checks every
   returned row's `tenant_id`.
- Vector search always filtered by tenant/project under RLS. Object-storage keys prefixed
  `tenant/{id}/project/{id}/…`.

## Prompt injection (§W)
WEBSITE CONTENT = UNTRUSTED DATA ≠ AGENT INSTRUCTIONS. Channel separation (content only in
delimited user-turn data blocks), out-of-band write authorization (executor runs approved
`plan_steps`), sanitisation before storage, sandboxed snapshot rendering. Injection corpus in the
eval suite from Phase 2.

## Crawler (§Phase 2)
SSRF guard (pre- and post-redirect IP validation, IP-pinned connections, scheme allow-list,
metadata-endpoint block), response size/time caps, crawl-budget + parametric-explosion caps,
sandboxed Playwright container.

## Audit
Every user and agent action → `audit_logs`. Every material autonomous decision → `agent_decisions`
(agent/prompt/model/tool versions + evidence + inputs + outputs + cost).

## CI
ruff (`S` rules on), mypy, dependency scan + SAST (Phase 13), `pip-audit`.
