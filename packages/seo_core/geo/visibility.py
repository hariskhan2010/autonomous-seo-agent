"""AI Visibility Score (A-TO-Z-PLAN.md §Phase 10 — deterministic).

A 0–100 score per (cluster, provider), always qualified by provider/model/locale — no blended
cross-provider number without the breakdown."""

from __future__ import annotations

from dataclasses import dataclass

from seo_core.geo.citations import Citation


@dataclass
class VisibilityScore:
    score: float
    brand_mention_rate: float
    own_citation_rate: float
    avg_brand_position: float | None
    competitor_share: float
    prompts_run: int


def visibility_score(citations: list[Citation]) -> VisibilityScore:
    n = len(citations) or 1
    mentions = sum(1 for c in citations if c.brand_mentioned)
    own_cites = sum(1 for c in citations if c.own_url_cited)
    positive = sum(1 for c in citations if c.sentiment == "positive")
    negative = sum(1 for c in citations if c.sentiment == "negative")
    positions = [c.brand_position for c in citations if c.brand_position]
    comp_total = sum(len(c.competitors_mentioned) for c in citations)

    mention_rate = mentions / n
    own_cite_rate = own_cites / n
    avg_pos = (sum(positions) / len(positions)) if positions else None
    # earlier mention is better (position 1 → +, position 5 → ~0)
    pos_bonus = max(0.0, (5 - (avg_pos or 5)) / 5) if avg_pos else 0.0
    sentiment_adj = (positive - negative) / n
    comp_share = comp_total / (comp_total + mentions) if (comp_total + mentions) else 0.0

    raw = (
        0.45 * mention_rate
        + 0.30 * own_cite_rate
        + 0.15 * pos_bonus
        + 0.10 * max(0.0, sentiment_adj)
    ) * 100
    raw *= (1 - 0.3 * comp_share)  # heavy competitor presence dilutes the score
    return VisibilityScore(
        score=round(max(0.0, min(100.0, raw)), 2),
        brand_mention_rate=round(mention_rate, 4),
        own_citation_rate=round(own_cite_rate, 4),
        avg_brand_position=round(avg_pos, 2) if avg_pos else None,
        competitor_share=round(comp_share, 4),
        prompts_run=len(citations),
    )
