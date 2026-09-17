"""RLS-policy-coverage gate (A-TO-Z-PLAN.md §Phase 12 acceptance).

Every application table must have RLS ENABLED + FORCED with a tenant-isolation policy — except
the three documented identity-global config tables. Fails if a new table is added without RLS."""

from __future__ import annotations

from sqlalchemy import text

from db.session import engine

GLOBAL_EXEMPT = {"users", "prompt_templates", "agent_versions", "alembic_version"}


def test_every_app_table_has_forced_rls() -> None:
    with engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT c.relname,
                   c.relrowsecurity AS enabled,
                   c.relforcerowsecurity AS forced,
                   (SELECT count(*) FROM pg_policies p WHERE p.tablename = c.relname) AS policies
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
        """)).all()

    missing = [
        r.relname for r in rows
        if r.relname not in GLOBAL_EXEMPT
        and not (r.enabled and r.forced and r.policies >= 1)
    ]
    assert not missing, f"tables without FORCED RLS + a policy: {missing}"

    # sanity: we actually checked a meaningful number of tables
    assert len(rows) >= 40
