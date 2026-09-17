# 0005 — Logical model roles, not hard-coded model names

- Status: accepted
- Date: 2026-09-06

## Context
Model names change often; hard-coding `claude-opus-5` / `claude-sonnet-5` across agents and code
makes provider/model changes a refactor (A-TO-Z-PLAN.md §H, §L).

## Decision
Code and agent definitions reference **roles**: `STRATEGY`, `WORKER`, `FAST`, `JUDGE`,
`EMBEDDING`. A single `config/model_registry.yaml` maps each role → provider + model + pinned
version + ordered fallback chain. `packages/llm` exposes one `LLMProvider` interface
(`complete`, `complete_structured`, `embed`).

Constraints enforced by the registry loader:
- `JUDGE` model family ≠ `WORKER` family (bias control).
- Every call records role, provider, model, model_version, prompt_version, agent_version.
- Structured outputs are schema-validated; one repair retry then fail.

## Consequences
- Swapping a provider = edit `model_registry.yaml` + an ADR; zero call-site changes.
- A `model_registry` DB table allows per-tenant overrides (Phase 12).

## Alternatives considered
- Env var per model: rejected — no fallback chain, no versioning, no bias constraint.
