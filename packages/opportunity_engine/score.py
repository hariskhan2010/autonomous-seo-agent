"""Opportunity scoring (A-TO-Z-PLAN.md §Phase 7, §25, §V — deterministic, no LLM).

`priority = business_impact × seo_impact × confidence × feasibility ÷ risk` → P0–P3.
Aligned with seo-agent/lib/scoring.py::score_one (same intent, cleaner inputs)."""

from __future__ import annotations


def priority_score(
    *, business_impact: float, seo_impact: float, confidence: float,
    feasibility: float, risk: float,
) -> float:
    risk = max(0.05, min(1.0, risk))
    raw = (
        _c(business_impact) * _c(seo_impact) * _c(confidence) * _c(feasibility)
    ) / risk
    return round(raw * 100, 3)


def _c(v: float) -> float:
    return max(0.0, min(1.0, v))


def bucket(score: float) -> str:
    if score >= 60:
        return "P0"
    if score >= 30:
        return "P1"
    if score >= 12:
        return "P2"
    return "P3"
