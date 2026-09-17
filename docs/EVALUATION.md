# Evaluation

Spec: `../A-TO-Z-PLAN.md` §P, §M. **Progressive** — the harness ships in Phase 1; every engine
phase adds golden data. Not a Phase 13 afterthought.

## Harness
`tests/eval/` — golden-set loader + scorecard runner. Runs in CI (smoke) + nightly (full) against
a fixed fixture site. Datasets in `tests/eval/golden/<domain>/`.

## Golden datasets by phase
| Phase | Dataset | Key metrics |
|---|---|---|
| 2 | crawler accuracy (fixture DOM/links/schema) | field-level precision/recall |
| 3 | SEO issue ledger | precision ≥ 0.9, recall ≥ 0.85 per check category |
| 4 | intent labels (≥200, multi-label) + clustering stability | per-class P/R, mixed-intent F1, cluster Jaccard |
| 5 | judge calibration + fact-check claim ledger | judge↔human correlation, unsupported-verdict precision |
| 7 | ranked opportunity list | rank correlation, P0/P1 precision |
| 8 | planner cases + guardrail red-team + verifier cases | tool-selection accuracy, guardrail trip rate, verifier FP/FN |
| 9 | seeded metric series with injected effect + confounder | effect detection / confounder rejection |
| 10 | ≥50 labelled AI responses | citation-parse P/R per provider |

## Rules
- **No LLM judge is the sole arbiter of factual correctness** — every factual metric has a
  deterministic or human-labelled ground truth.
- An agent below threshold on precision or verification-correctness is auto-demoted to assisted
  mode for its change classes until it recovers.
