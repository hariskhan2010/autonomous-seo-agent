"""SERP intelligence (A-TO-Z-PLAN.md §Phase 4, §10 — deterministic).

Turns a normalised `SerpPayload` into a `SerpAnalysis`: top domains, feature inventory, PAA/
related questions, entity/topic mining from titles+snippets, and a content-gap list (topics the
ranking pages cover that a given page does not)."""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlsplit

from seo_core.keywords.normalize import tokens
from seo_core.serp.models import SerpAnalysis, SerpPayload

_STOP = {
    "with", "your", "from", "this", "that", "have", "will", "what", "when", "which", "guide",
    "best", "how", "and", "the", "for", "you", "are", "our", "can", "get", "top", "vs",
}


def _domain(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.")


def _phrases(text: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z][a-z'-]{2,}", text.lower()) if w not in _STOP]
    out = list(words)
    out += [f"{a} {b}" for a, b in zip(words, words[1:], strict=False)]
    return out


def analyze_serp(
    payload: SerpPayload,
    *,
    own_domain: str | None = None,
    competitor_domains: list[str] | None = None,
    page_text: str | None = None,
) -> SerpAnalysis:
    competitors = {d.removeprefix("www.") for d in (competitor_domains or [])}
    top_domains: list[str] = []
    own_pos: int | None = None
    comp_pos: dict[str, int] = {}
    for item in sorted(payload.organic, key=lambda i: i.position):
        d = _domain(item.url)
        if d and d not in top_domains:
            top_domains.append(d)
        if own_domain and d == own_domain.removeprefix("www.") and own_pos is None:
            own_pos = item.position
        if d in competitors and d not in comp_pos:
            comp_pos[d] = item.position

    feature_types = sorted({f.type for f in payload.features})
    questions: list[str] = []
    for f in payload.features:
        if f.type == "people_also_ask":
            questions.extend(f.items)
    questions.extend(q for q in payload.related_searches if q.endswith("?"))

    corpus = " ".join(f"{i.title} {i.snippet}" for i in payload.organic)
    counts = Counter(_phrases(corpus))
    entities = [(term, round(c / max(1, len(payload.organic)), 3))
                for term, c in counts.most_common(20) if c >= 2]
    common_topics = [t for t, _ in entities[:12]]

    content_gap: list[str] = []
    if page_text is not None:
        have = tokens(page_text)
        for topic in common_topics:
            if not set(topic.split()) & have:
                content_gap.append(topic)

    return SerpAnalysis(
        query=payload.query,
        top_domains=top_domains[:10],
        feature_types=feature_types,
        questions=questions[:15],
        entities=entities,
        common_topics=common_topics,
        own_position=own_pos,
        competitor_positions=comp_pos,
        content_gap=content_gap,
    )
