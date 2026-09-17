"""Row-Level-Security policy helpers for migrations (A-TO-Z-PLAN.md §F.2).

Contract:
- Every application table has RLS ENABLED and FORCED (so the table owner is not exempt —
  Neon's `neondb_owner` has BYPASSRLS, and `FORCE` is the guard).
- Isolation key: `current_setting('app.tenant_id', true)::uuid`. Project-scoped tables may add
  `current_setting('app.project_id', true)::uuid`.
- The runtime role (`seo_app`) is NOBYPASSRLS; the API/worker sets these GUCs per request/job.

`tenant_session(tenant_id)` with no `project_id` (every tenant-only API route — most of them; a
project_id isn't always in the URL) sets `app.project_id` to `''`, not unset. PostgreSQL does NOT
guarantee left-to-right OR evaluation, so a bare `current_setting(...) = '' OR project_id =
current_setting(...)::uuid` predicate can still attempt (and fail) the `''::uuid` cast depending
on how the planner orders the disjuncts — `NULLIF(x, '')` collapses `''` to `NULL` *before* the
cast, and `NULL::uuid` never errors, so the cast is safe regardless of evaluation order."""

from __future__ import annotations

from alembic import op

RUNTIME_ROLE = "seo_app"
READONLY_ROLE = "seo_readonly"


def policy_predicate(*, project_scoped: bool) -> str:
    tenant_pred = "tenant_id = current_setting('app.tenant_id', true)::uuid"
    if not project_scoped:
        return tenant_pred
    return (
        f"({tenant_pred} AND "
        "(NULLIF(current_setting('app.project_id', true), '') IS NULL "
        "OR project_id = NULLIF(current_setting('app.project_id', true), '')::uuid))"
    )


def enable(table: str, *, project_scoped: bool = False) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    pred = policy_predicate(project_scoped=project_scoped)
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        f"USING ({pred}) WITH CHECK ({pred})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {RUNTIME_ROLE}")
    op.execute(f"GRANT SELECT ON {table} TO {READONLY_ROLE}")


def redefine(table: str, *, project_scoped: bool = False) -> None:
    """Drops and recreates `{table}_tenant_isolation` with the current `policy_predicate` —
    for fixing a policy on a table whose RLS is already enabled (see migration 0012)."""
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    pred = policy_predicate(project_scoped=project_scoped)
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        f"USING ({pred}) WITH CHECK ({pred})"
    )


def disable(table: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
