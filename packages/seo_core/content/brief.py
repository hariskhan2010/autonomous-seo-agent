"""Content brief generation (A-TO-Z-PLAN.md §Phase 5).

Deterministic skeleton from keyword + SERP evidence (analysis). An LLM `WORKER` pass can enrich
the angle/talking-points later — the structure + evidence citations come from here."""

from __future__ import annotations

from dataclasses import dataclass, field

from seo_core.serp.models import SerpAnalysis


@dataclass
class ContentBrief:
    keyword: str
    target_word_count: int
    suggested_headings: list[str] = field(default_factory=list)
    questions_to_answer: list[str] = field(default_factory=list)
    entities_to_cover: list[str] = field(default_factory=list)
    competitor_urls: list[str] = field(default_factory=list)
    evidence_serp_run_id: str | None = None


def build_brief(
    keyword: str, analysis: SerpAnalysis, *, serp_run_id: str | None = None,
    competitor_avg_words: int | None = None,
) -> ContentBrief:
    target = competitor_avg_words or 900
    headings = [f"What is {keyword}?"] if not analysis.common_topics else [
        t.title() for t in analysis.common_topics[:8]
    ]
    return ContentBrief(
        keyword=keyword,
        target_word_count=max(500, min(3000, target)),
        suggested_headings=headings,
        questions_to_answer=analysis.questions[:10],
        entities_to_cover=[t for t, _ in analysis.entities[:15]],
        competitor_urls=[f"https://{d}/" for d in analysis.top_domains[:5]],
        evidence_serp_run_id=serp_run_id,
    )
