# 0004 — Auth backend

- Status: proposed (decide before Phase 1 auth work)
- Date: 2026-09-06

## Context
Need email + Google OAuth login, JWT carrying `user_id` / `tenant_id` / roles, and RBAC+ABAC on
every endpoint (A-TO-Z-PLAN.md §Phase 1). The original prototype dashboard used
Supabase Auth.

## Options
1. **Keep Supabase Auth** — reuse dashboard integration, hosted, Google OAuth built in. Adds a
   vendor; JWT verification in FastAPI via Supabase JWKS.
2. **FastAPI-Users + JWT** — no vendor, full control, more code (password reset, OAuth flows,
   email delivery).

## Recommendation
Start with **Supabase Auth** (option 1) to reach Production V1 faster; the API only needs to
verify the JWT and map claims → tenant session. Revisit if multi-tenant SaaS billing/SSO needs
outgrow it. Decision owner: project lead.

## Consequences
- `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_KEY` in the secret set.
- Tenant/project membership tables still live in our Postgres; Supabase is identity only.
