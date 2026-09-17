"""0012 fix RLS project-scope cast

A pre-existing bug in every project-scoped RLS policy (`db.rls.enable`): a tenant-only session
(`tenant_session(tenant_id)` with no `project_id` — the shape of most API routes, since a
project_id isn't always in the URL) sets the `app.project_id` GUC to `''`, not unset. The old
policy predicate was `current_setting('app.project_id', true) = '' OR project_id =
current_setting('app.project_id', true)::uuid` — PostgreSQL does not guarantee left-to-right OR
evaluation, so the planner can still attempt (and fail) the `''::uuid` cast in the second disjunct
even when the first is true, raising `invalid input syntax for type uuid: ""` on ANY query against
ANY project-scoped table made through a tenant-only session. Confirmed failing against this exact
Neon database (`SELECT ... FROM plans WHERE plans.id = ...` via `/v1/plans/{id}/approve`).

Fix: `NULLIF(current_setting('app.project_id', true), '')` collapses `''` to `NULL` *before* the
cast; `NULL::uuid` never errors, so the cast is safe regardless of evaluation order (see
`db.rls.policy_predicate`). This migration re-points every existing project-scoped policy at the
fixed predicate — no schema/data change, so `redefine` (drop + recreate the same policy) is safe
to run against a live table.

Revision ID: 81470a3a36a8
Revises: c7b68f2e41b5
Create Date: 2026-09-12 16:52:42.406837
"""
from __future__ import annotations

from collections.abc import Sequence

from db.rls import redefine as rls_redefine

revision: str = '81470a3a36a8'
down_revision: str | None = 'c7b68f2e41b5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every table ever registered with `rls_enable(..., project_scoped=True)` (migrations 0001-0010).
_PROJECT_SCOPED_TABLES = [
    # 0001 foundation
    "websites", "urls", "pages", "evidence", "evidence_links",
    # 0002 crawl
    "crawl_runs", "page_snapshots", "crawl_results",
    # 0003 seo_issues
    "seo_issues",
    # 0004 keywords/serp
    "keyword_clusters", "keywords", "search_intents", "keyword_page_map",
    "serp_runs", "serp_results", "serp_features", "serp_entities",
    # 0005 content
    "topics", "entities", "content_items", "content_scores",
    # 0006 knowledge graph
    "kg_nodes", "kg_edges", "embeddings",
    # 0007 opportunities
    "opportunities",
    # 0008 safety spine
    "plans", "plan_steps", "approvals", "changes", "change_versions", "verifications",
    "rollbacks", "incidents", "agent_decisions",
    # 0009 analytics
    "metric_snapshots", "anomalies", "experiments", "learnings", "opportunity_weights",
    "memory_entries",
    # 0010 geo
    "ai_prompts", "ai_prompt_runs", "ai_responses", "ai_citations", "ai_visibility_scores",
]


def upgrade() -> None:
    for t in _PROJECT_SCOPED_TABLES:
        rls_redefine(t, project_scoped=True)


def downgrade() -> None:
    # Restores the exact pre-0012 predicate (byte-for-byte) so this round-trips cleanly. Its
    # `''::uuid` cast hazard is exactly the bug 0012 fixes — this is a deliberate historical
    # reproduction for a clean downgrade, not a recommendation to use it.
    from alembic import op

    for t in _PROJECT_SCOPED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {t}_tenant_isolation ON {t}")
        pred = (
            "(tenant_id = current_setting('app.tenant_id', true)::uuid AND "
            "(current_setting('app.project_id', true) IS NULL OR "
            "current_setting('app.project_id', true) = '' OR "
            "project_id = current_setting('app.project_id', true)::uuid))"
        )
        op.execute(f"CREATE POLICY {t}_tenant_isolation ON {t} USING ({pred}) WITH CHECK ({pred})")
