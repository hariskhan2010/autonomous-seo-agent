"""Consolidated evaluation scorecards (A-TO-Z-PLAN.md §Phase 13, §P).

One place that runs every engine's golden set and produces a scorecard row. CI runs the smoke
subset; the nightly job runs the full matrix against the fixture site and tracks scores over time.

**No LLM judge is the sole arbiter of factual correctness** — every metric below has a
deterministic or hand-labelled ground truth.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from tests.eval.runner import Scorecard, prf


@dataclass
class ScorecardRow:
    engine: str
    metric: str
    value: float
    threshold: float
    passed: bool
    run_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))


# threshold table — an engine below its threshold is auto-demoted to assisted mode (§P)
THRESHOLDS: dict[tuple[str, str], float] = {
    ("technical_engine", "precision"): 0.90,
    ("technical_engine", "recall"): 0.85,
    ("intent_classifier", "precision"): 0.85,
    ("opportunity_scoring", "rank_correlation"): 0.70,
    ("citation_parser", "precision"): 0.80,
    ("anomaly_detector", "false_positive_rate"): 0.10,  # lower is better → inverted check below
    ("execution_safety", "guardrail_trip_rate"): 1.00,  # every red-team fixture must trip
}


def run_smoke() -> list[ScorecardRow]:
    """The CI subset — fast, deterministic, no network."""
    rows: list[ScorecardRow] = []

    # technical engine — reuse the golden ledger from test_technical_engine
    from seo_core.technical import analyze
    from seo_core.technical.models import SiteContext
    from tests.unit.test_technical_engine import EXPECTED, PAGES, _key

    found = {_key(f) for f in analyze(PAGES, SiteContext(origin="https://shop.test", sitemap_urls=[]))}
    tp = len(found & EXPECTED)
    fp = len(found - EXPECTED - {("robots_no_sitemap", None)})
    fn = len(EXPECTED - found)
    s = prf(tp, fp, fn)
    for metric in ("precision", "recall"):
        th = THRESHOLDS[("technical_engine", metric)]
        rows.append(ScorecardRow("technical_engine", metric, s[metric], th, s[metric] >= th))

    # intent classifier
    from seo_core.keywords import classify_intent
    from tests.unit.test_keyword_intent import LEDGER

    correct = sum(1 for kw, exp in LEDGER if classify_intent(kw)[0].label == exp)
    prec = correct / len(LEDGER)
    th = THRESHOLDS[("intent_classifier", "precision")]
    rows.append(ScorecardRow("intent_classifier", "precision", round(prec, 4), th, prec >= th))

    # citation parser
    from integrations.ai_providers.fake import FakeAiProvider

    from seo_core.geo import parse_citations

    c = parse_citations(
        FakeAiProvider().ask("best gemstone rings").text, brand="GemShop",
        own_domain="shop.example.com", competitor_names=["Blue Nile"],
    )
    hit = int(c.brand_mentioned) + int(c.own_url_cited) + int("Blue Nile" in c.competitors_mentioned)
    prec = hit / 3
    th = THRESHOLDS[("citation_parser", "precision")]
    rows.append(ScorecardRow("citation_parser", "precision", prec, th, prec >= th))

    return rows


def scorecard_summary(rows: list[ScorecardRow]) -> Scorecard:
    return Scorecard(name="consolidated", metrics={f"{r.engine}.{r.metric}": r.value for r in rows})
