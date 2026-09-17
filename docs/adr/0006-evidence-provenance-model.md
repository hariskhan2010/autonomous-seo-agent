# 0006 — Evidence & provenance model

- Status: accepted
- Date: 2026-09-06

## Context
Pillar 1: no finding without a stored, hashed, provider-attributed artifact. Issues,
opportunities, recommendations, KG edges, and agent decisions must all trace to evidence
(A-TO-Z-PLAN.md §F.1, §B).

## Decision
- `evidence` table: source URL, method, http_status, run lineage (`crawl_run_id` /
  `serp_run_id` / `ai_prompt_run_id`), `snapshot_id` (object-storage pointer), `content_hash`
  (sha256, dedupe key), `provider`, `parser` + `parser_version`, `collected_at`, `confidence`,
  `props`. `unique(tenant_id, content_hash, kind)`.
- `evidence_links` — polymorphic M:N: `evidence_id` ↔ `(subject_type, subject_id)` where
  `subject_type ∈ {issue, opportunity, recommendation, kg_edge, agent_decision, verification,
  learning}`. **Many evidence rows may back one subject.**
- Raw bytes → object storage; `evidence` holds only hash + pointer + metadata.
- Write-time rule: a finding with zero `evidence_links` is rejected (service check + FK).
- `confidence` is produced by the ported `seo_core/confidence.py` (source × freshness × cross-check).

## Consequences
- Every analyzer and every LLM step must emit evidence rows — this shapes their return contracts.
- `opportunity_evidence` becomes a convenience view over `evidence_links`.

## Alternatives considered
- Per-subject evidence FK columns: rejected — can't express many-to-one or share evidence across
  subject types.
