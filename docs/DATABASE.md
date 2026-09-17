# Database

Full table list: `../A-TO-Z-PLAN.md` §F. ERD is generated (`make erd`, wired in Phase 1).

## Conventions
- Every table: `id uuid pk default gen_random_uuid()`, `tenant_id uuid not null`,
  `created_at timestamptz not null default now()`.
- Project-scoped tables also: `project_id uuid not null`.
- Every table: RLS policy on `current_setting('app.tenant_id')::uuid` (and `app.project_id`
  where relevant) + `ALTER TABLE … FORCE ROW LEVEL SECURITY`.
- Migrations run as `seo_migrator` (owns schema). Runtime uses `seo_rw` / `seo_ro`
  (NOSUPERUSER, NOBYPASSRLS, own nothing).
- Composite indexes lead with `(tenant_id, project_id, …)`. BRIN on `created_at` for append-only
  logs. No partitioning before ~50M rows (§F.5).

## Migration order (incremental)
| Migration | Tables | Phase |
|---|---|---|
| 0001 | tenants, users, memberships, projects, websites, pages, urls, audit_logs, evidence, evidence_links, outbox_events, processed_events, resource_locks, job_runs, prompt_templates, agent_versions, model_registry | 1 |
| 0002 | crawl_runs, page_snapshots, crawl_results, tool_calls | 2 |
| 0003 | seo_issues | 3 |
| 0004 | keywords, keyword_clusters, search_intents, keyword_page_map, serp_runs, serp_results, serp_features, serp_entities | 4 |
| 0005 | topics, entities, content_items, content_scores | 5 |
| 0006 | kg_nodes, kg_edges, embeddings, embedding_jobs | 6 |
| 0007 | opportunities | 7 |
| 0008 | plans, plan_steps, approvals, changes, change_versions, verifications, rollbacks, incidents, agent_decisions | 8 |
| 0009 | metric_snapshots, anomalies, experiments, learnings, opportunity_weights, memory_entries | 9 |
| 0010 | ai_prompts, ai_prompt_runs, ai_responses, ai_citations, ai_visibility_scores | 10 |
| 0011 | dead_letter_events, schedules, agent_runs | 11 |
| 00xx | metrics, metric_snapshots, experiments*, learnings, memory_* | 9 |
| 00xx | ai_prompts, ai_prompt_runs, ai_responses, ai_citations | 10 |
| 00xx | schedules, events | 11 |

## Extensions
`pgcrypto`, `vector` (pgvector), `pg_trgm`. Enabled by `infra/db-init/01-extensions.sql` in dev;
by migration 0001 in managed environments.
