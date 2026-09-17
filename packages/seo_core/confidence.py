"""Evidence-weighted confidence (ported from seo-agent/utils/confidence.py).

Central to Pillar 1 (A-TO-Z-PLAN.md §B, §F.1): this produces the `evidence.confidence` value.
`score()` combines source authority × freshness × cross-checking × completeness — deterministic,
no LLM (§V)."""

from __future__ import annotations

import datetime

# source key -> (human label, base confidence, is a live/first-hand source)
CONFIDENCE_RULES: dict[str, tuple[str, float, bool]] = {
    "gsc": ("Google Search Console API", 0.99, True),
    "ga4": ("Google Analytics 4 API", 0.99, True),
    "pagespeed": ("PageSpeed Insights API", 0.95, True),
    "crux": ("Chrome UX Report API", 0.95, True),
    "serpapi": ("SerpAPI live SERP", 0.93, True),
    "dataforseo": ("DataForSEO API", 0.95, True),
    "ahrefs": ("Ahrefs API", 0.95, True),
    "semrush": ("Semrush API", 0.95, True),
    "crawl": ("First-hand crawl fetch", 0.98, True),
    "rendered_dom": ("Rendered DOM (headless browser)", 0.97, True),
    "ai_response": ("AI provider response", 0.85, True),
    "llm": ("LLM analysis", 0.80, False),
    "heuristic": ("Rule-based heuristic", 0.85, False),
    "estimate": ("Estimate", 0.60, False),
    "unknown": ("No data available", 0.10, False),
}

Label = str


def score(
    source: str,
    *,
    age_days: float | None = None,
    cross_checked: bool = False,
    partial: bool = False,
) -> float:
    _, base, _ = CONFIDENCE_RULES.get(source, CONFIDENCE_RULES["unknown"])
    value = base
    if age_days is not None:
        if age_days > 365:
            value -= 0.20
        elif age_days > 90:
            value -= 0.10
        elif age_days > 30:
            value -= 0.05
    if cross_checked:
        value = min(0.99, value + 0.04)
    if partial:
        value -= 0.15
    return max(0.01, min(0.99, round(value, 3)))


def label(value: float) -> Label:
    if value >= 0.90:
        return "HIGH"
    if value >= 0.70:
        return "MEDIUM"
    return "LOW"


def is_firsthand(source: str) -> bool:
    return CONFIDENCE_RULES.get(source, CONFIDENCE_RULES["unknown"])[2]


def provenance_note() -> dict[str, str]:
    return {
        "generated_at": datetime.datetime.now(tz=datetime.UTC).isoformat(),
        "note": "Confidence reflects data source, freshness, cross-checking, and completeness.",
    }
