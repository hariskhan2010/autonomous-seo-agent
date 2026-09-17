# Agents

Spec: `../A-TO-Z-PLAN.md` §H. The original 9 role markdown specs lived in the now-deleted
`seo-agent/agents/`; recreate each here as a versioned system prompt + skill manifest + role
binding.

## Structure (`packages/agents/<name>/`)
- `system.md` — versioned system prompt (static, no fetched content), content-hashed →
  `prompt_templates`.
- `manifest.yaml` — `agent_version`, `model_role`, `allowed_tools`, `escalation`, change classes.
- `agent.py` — thin adapter: assemble evidence (user turn), call `packages/llm`, validate output.

## Logical roles → model (config/model_registry.yaml)
`STRATEGY` (orchestration, planning, major content) · `WORKER` (analysis, drafting) ·
`FAST` (classification, extraction, aggregation) · `JUDGE` (rubric scoring — different family
from WORKER) · `EMBEDDING`.

## Roster (agent → primary role)
Orchestrator→STRATEGY · Technical/Crawler/Keywords/SERP/Content/Topical/InternalLinks/
Competitors/Backlinks/Local/Ecommerce/International/Analytics/GEO → WORKER (Crawler & Keywords
also use FAST; Content escalates to STRATEGY) · ContentJudge/FactChecker → JUDGE.

## Rules
- The Orchestrator has **no** write tools — it delegates only.
- Every material decision writes an `agent_decisions` row (reproducibility, §Y).
- LLM output that drives execution is schema-validated; writes above LOW_RISK_WRITE are human-gated.
