"""Search-intent engine (A-TO-Z-PLAN.md §Phase 4, §9).

Rule-based multi-label classifier over the 12 intent classes, with a confidence per label.
Ported and expanded from seo-agent/lib/clustering.py::classify_intent. The `WORKER`/`FAST` model
classifier for ambiguous cases plugs in later — this is the deterministic floor (§V)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class IntentLabel(StrEnum):
    INFORMATIONAL = "informational"
    NAVIGATIONAL = "navigational"
    COMMERCIAL = "commercial"
    TRANSACTIONAL = "transactional"
    LOCAL = "local"
    VISUAL = "visual"
    VIDEO = "video"
    NEWS = "news"
    QUESTION = "question"
    COMPARISON = "comparison"
    HOW_TO = "how_to"
    DEFINITIONAL = "definitional"


# marker -> weight. Substring match on the normalised keyword.
_MARKERS: dict[IntentLabel, dict[str, float]] = {
    IntentLabel.TRANSACTIONAL: {
        "buy": 1.0, "cheap": 0.8, "price": 0.9, "cost": 0.7, "for sale": 1.0, "deal": 0.7,
        "discount": 0.8, "coupon": 0.9, "order": 0.8, "shop": 0.6, "purchase": 1.0, "under $": 0.9,
    },
    IntentLabel.COMMERCIAL: {
        "best": 0.9, "top": 0.7, "review": 0.9, "reviews": 0.9, "rated": 0.7, "brands": 0.7,
        "alternative": 0.8, "alternatives": 0.8, "recommended": 0.7, " for ": 0.3,
    },
    IntentLabel.COMPARISON: {" vs ": 1.0, " vs. ": 1.0, "compare": 0.9, "comparison": 0.9, "difference between": 0.9},
    IntentLabel.NAVIGATIONAL: {"login": 1.0, "log in": 1.0, "sign in": 1.0, "official": 0.8, "website": 0.5, "portal": 0.7},
    IntentLabel.LOCAL: {"near me": 1.0, "in ": 0.2, "nearby": 0.9, "directions": 0.8, "store hours": 0.9, "open now": 0.9},
    IntentLabel.HOW_TO: {"how to": 1.0, "how do": 0.9, "how can": 0.8, "steps to": 0.8, "guide to": 0.6, "tutorial": 0.9},
    IntentLabel.DEFINITIONAL: {"what is": 1.0, "what are": 0.9, "meaning": 0.9, "definition": 1.0, "means": 0.6},
    IntentLabel.QUESTION: {"why": 0.8, "who": 0.6, "when": 0.6, "where": 0.6, "which": 0.6, "can you": 0.7, "should i": 0.8, "?": 0.9},
    IntentLabel.VIDEO: {"video": 0.95, "watch video": 0.9, "youtube": 1.0, "trailer": 0.9, "footage": 0.85},
    IntentLabel.VISUAL: {"images": 0.9, "photos": 0.8, "pictures": 0.8, "wallpaper": 0.9, "logo": 0.7, "chart": 0.6},
    IntentLabel.NEWS: {"news": 0.9, "latest": 0.7, "update": 0.5, "today": 0.5, "breaking": 0.9, "2026": 0.4},
}

_QUESTION_RE = re.compile(r"^(how|what|why|who|when|where|which|can|does|do|is|are|should)\b")


@dataclass(frozen=True)
class Scored:
    label: IntentLabel
    confidence: float
    method: str = "rule"


def classify_intent(keyword: str, *, threshold: float = 0.35, max_labels: int = 3) -> list[Scored]:
    k = f" {keyword.casefold().strip()} "
    scores: dict[IntentLabel, float] = {}
    for label, markers in _MARKERS.items():
        hit = 0.0
        for marker, weight in markers.items():
            if marker in k:
                hit = max(hit, weight)
        if hit:
            scores[label] = hit

    if _QUESTION_RE.match(keyword.casefold().strip()):
        scores[IntentLabel.QUESTION] = max(scores.get(IntentLabel.QUESTION, 0.0), 0.7)

    # no strong signal → informational is the prior
    if not scores or max(scores.values()) < threshold:
        return [Scored(IntentLabel.INFORMATIONAL, 0.5)]

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top = ranked[0][1]
    out = [
        Scored(label, round(min(0.99, v), 3))
        for label, v in ranked
        if v >= threshold and v >= top * 0.6
    ][:max_labels]
    return out or [Scored(IntentLabel.INFORMATIONAL, 0.5)]


def primary_intent(keyword: str) -> IntentLabel:
    return classify_intent(keyword)[0].label
