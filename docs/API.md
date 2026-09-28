# API

Spec: `../A-TO-Z-PLAN.md` §Phase 1, §Phase 12, §24. OpenAPI is the contract:
`GET /v1/openapi.json` (schemathesis in CI).

## Conventions
- All routes under `/v1`. Future breaking changes → `/v2` with a deprecation window.
- Auth: OAuth2/JWT (bearer) or per-tenant API key. JWT claims: `user_id`, `tenant_id`, roles.
- Authz: RBAC (`owner/admin/operator/viewer`) + ABAC (`project_id` membership). Each route
  declares required role + scope.
- Pagination: keyset cursor (`?limit=&cursor=`, `app/pagination.py`). The existing list
  endpoints (`crawls`, `issues`, `anomalies`, `experiments`, `geo/visibility`, `opportunities`,
  `changes`) keep their bare-array body for backward compatibility; the next page's cursor is in
  the `X-Next-Cursor` header (+ `Link: <…>; rel="next"`), absent on the last page. Omitting both
  params keeps the legacy full listing (`crawls` keeps its default `limit=20`). `/keywords`
  (object body) returns `next_cursor` in the body. A cursor is only valid for the endpoint that
  minted it (400 otherwise). New endpoints should use the `{ data: [...], next_cursor }` shape.
- Mutations accept `Idempotency-Key` header → stored in `job_runs`; replay returns prior result
  (same status, `Idempotent-Replayed: true`); same key + different body → 422; failed requests
  are not recorded. Wired on `POST /projects`, `POST /websites`, `POST /plans/{id}/approve`
  (`app/idempotency.py`).
- Long operations (crawl, audit, GEO battery): `202 Accepted` + `{ job_id, status_url }`;
  completion via webhook (HMAC + timestamp signed) or poll.
- Rate limits per key + per tenant → `429` + `Retry-After`.
- Error envelope: `{ "error": { "code": "...", "message": "...", "details": {...} } }`.

## Surface (built incrementally)
Phase 1: `/v1/health`, `/v1/projects`, `/v1/websites`, `/v1/projects/{id}/config`.
Phase 12: crawls, issues, opportunities, keywords, serps, content, competitors, backlinks,
analytics, agents, tasks, changes, approvals, experiments, reports.

## Inbound webhooks
Signature-verified (provider secret). Unverified payloads rejected before processing.
