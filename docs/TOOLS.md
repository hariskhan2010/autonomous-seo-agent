# Tool registry

Spec: `../A-TO-Z-PLAN.md` §I. Tools are the **only** way an agent touches the world — no raw
shell, DB, filesystem, or network in any agent runtime.

## Descriptor (enforced at registration and call time)
| Field | Meaning |
|---|---|
| `name`, `version` (semver) | identity; version recorded on every call |
| `input_schema` / `output_schema` | JSON Schema; validated in and out |
| `risk` | `READ_ONLY` / `LOW_RISK_WRITE` / `HIGH_RISK_WRITE` / `IRREVERSIBLE_EXTERNAL_ACTION` (§K.1) |
| `allowed_agents` | allow-list; other callers refused + audited |
| `scope` | `tenant` / `project` — tool cannot widen its context |
| `rate_limit`, `timeout`, `retry_policy` | enforced by the runtime, not the tool body |
| `permission` | `auto` / `approval_required` (auto only for READ_ONLY + allowlisted LOW_RISK_WRITE) |
| `side_effect_key` | idempotency key for write tools |
| `audit` | always on — every call writes a `tool_calls` row |

## Trust boundary
Tool results are typed data, never instructions (§W). Web-fetched content is wrapped
`EXTERNAL_UNTRUSTED` before any agent sees it. A write tool call is validated against the
approved `plan_steps` — an agent cannot invent a new write target mid-run.

## Families (built across phases)
`crawl_site`, `fetch_url`, `render_page`, `parse_sitemap`, `parse_robots` · `analyze_schema`,
`analyze_links` · `search_keywords`, `search_serp` · `get_gsc_data`, `get_analytics` ·
`analyze_backlinks`, `analyze_competitor` · `query_ai_provider` · `update_cms`, `create_content`,
`modify_metadata`, `verify_change`, `rollback_change`.

## Registry location
`packages/tools/registry.py` — descriptors + dispatch. First tools land in Phase 2; write tools
in Phase 8.
