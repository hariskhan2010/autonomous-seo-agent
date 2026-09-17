"""Deterministic content quality score (A-TO-Z-PLAN.md §Phase 5, §V).

Ported from seo-agent/lib/scoring.py::score_article. 0-100 with a PASS/REVISE/FAIL verdict.
This is the rule floor the LLM judge is checked against — never the sole arbiter."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_H2_RE = re.compile(r"^##\s+.+$", re.M)
_LINK_RE = re.compile(r"\[[^\]]+\]\((/[^)]+|https?://[^)]+)\)")


@dataclass
class QualityScore:
    score: int
    verdict: str
    checks: dict[str, float] = field(default_factory=dict)


def _kw_count(text: str, kw: str) -> int:
    return text.lower().count(kw.lower())


def score_article(
    text: str, *, keyword: str | None = None, target_words: int = 700,
    expected_headings: list[str] | None = None,
) -> QualityScore:
    t = (text or "").lower()
    checks: dict[str, float] = {}
    total = 0.0

    words = len(t.split())
    checks["word_count"] = 20 if words >= target_words * 0.9 else (12 if words >= target_words * 0.6 else 5)
    total += checks["word_count"]

    if keyword and keyword.lower() in t[:500]:
        checks["kw_in_opening"] = 15
    elif keyword and keyword.lower() in t:
        checks["kw_in_opening"] = 8
    else:
        checks["kw_in_opening"] = 0
    total += checks["kw_in_opening"]

    for heading in expected_headings or []:
        if heading.lower() in t:
            checks[f"covers:{heading[:24]}"] = 5
            total += 5

    h2 = len(_H2_RE.findall(text or ""))
    checks["h2_headings"] = h2
    total += 15 if h2 >= 3 else (8 if h2 >= 1 else 0)

    internal = len(_LINK_RE.findall(text or ""))
    checks["internal_links"] = internal
    total += 15 if internal >= 3 else (7 if internal >= 1 else 0)

    if keyword and keyword.lower() in t:
        c = _kw_count(t, keyword)
        checks["kw_mentions"] = c
        total += min(10, c * 2)

    score = round(min(100.0, total))
    verdict = "PASS" if score >= 70 else ("REVISE" if score >= 45 else "FAIL")
    return QualityScore(score=score, verdict=verdict, checks=checks)
