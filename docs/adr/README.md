# Architecture Decision Records

One file per decision. Status: `proposed` | `accepted` | `superseded by NNNN`.
The exhaustive rationale lives in `../../A-TO-Z-PLAN.md`; ADRs record the decision + why + consequences.

| # | Title | Status |
|---|---|---|
| 0001 | Monorepo layout | accepted |
| 0002 | PostgreSQL knowledge graph first (no Neo4j) | accepted |
| 0003 | Celery + Temporal — distinct non-overlapping roles | accepted |
| 0004 | Auth backend (Supabase Auth vs FastAPI-Users) | proposed |
| 0005 | Logical model roles, not hard-coded model names | accepted |
| 0006 | Evidence & provenance model | accepted |
| 0007 | Transactional outbox for events | accepted |

## Template

```
# NNNN — Title
- Status: proposed | accepted | superseded by NNNN
- Date: YYYY-MM-DD

## Context
## Decision
## Consequences
## Alternatives considered
```
