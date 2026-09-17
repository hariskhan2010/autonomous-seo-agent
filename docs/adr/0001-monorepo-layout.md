# 0001 — Monorepo layout

- Status: accepted
- Date: 2026-09-06

## Context
The starting code (`seo-agent/`) is argparse scripts + a Next.js dashboard. The target is an
autonomous operating system: API, worker, deterministic analyzer libraries, agent definitions,
a safety spine, integrations, and MCP servers. These share models, config, and the evidence
contract and must version together.

## Decision
Single monorepo `autonomous-seo-agent/` (A-TO-Z-PLAN.md §E):
- `apps/` — deployable units (`api`, `worker`, `dashboard`).
- `packages/` — importable libraries; `seo_core` is pure/deterministic/tenant-agnostic.
- `packages/common/` — cross-cutting: settings, logging, redaction, db session (added in Phase 0).
- `integrations/` — external-provider clients. `mcp/` — MCP servers. `database/` — Alembic.
- Python managed by **uv** (`package = false`; `packages` + `apps/*` on `pythonpath`).

## Consequences
- One `pyproject.toml`, one venv, one CI pipeline, atomic cross-cutting changes.
- `seo-agent/` (the original argparse scripts + Next.js dashboard) has been **deleted** — all
  deterministic logic is ported into `packages/seo_core`; the dashboard will be rebuilt fresh
  against the `/v1` read API in Phase 12.
- Import paths are flat (`from seo_core...`, `from common...`); enforced by ruff isort + mypy.

## Alternatives considered
- Polyrepo: rejected — the evidence/model contract churns across every package early on.
- src/ layout single package: rejected — `apps` and `packages` have different lifecycles.
