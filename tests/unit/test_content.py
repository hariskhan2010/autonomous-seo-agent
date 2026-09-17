from __future__ import annotations

import datetime as dt

from seo_core.content import (
    build_brief,
    cannibalization_groups,
    classify_content_type,
    content_flags,
    rule_judge,
    score_article,
)
from seo_core.content.signals import ContentRow
from seo_core.serp.models import SerpAnalysis

UTC = dt.UTC


def test_content_type_classification() -> None:
    assert classify_content_type(url="https://x.com/") == "home"
    assert classify_content_type(url="https://x.com/product/ring-1", has_price=True) == "product"
    assert classify_content_type(url="https://x.com/collections/rings") == "category"
    assert classify_content_type(url="https://x.com/blog/how-to-clean", word_count=800) == "article"


def test_quality_score_thresholds() -> None:
    good = "# Title\n\n## One\n\n## Two\n\n## Three\n\n" + "gemstone ring " * 200 + "[link](/a) [b](/b) [c](/c)"
    weak = "short text about nothing much"
    assert score_article(good, keyword="gemstone ring", target_words=300).verdict == "PASS"
    assert score_article(weak, keyword="gemstone ring").verdict == "FAIL"


def test_flags_thin_and_orphan() -> None:
    thin = ContentRow(url="/a", content_type="article", word_count=50, internal_links_in=0)
    assert set(content_flags(thin)) >= {"thin", "orphan"}


def test_flags_outdated() -> None:
    old = ContentRow(url="/a", content_type="article", word_count=900, internal_links_in=3,
                     updated_at=dt.datetime(2022, 1, 1, tzinfo=UTC))
    assert "outdated" in content_flags(old, now=dt.datetime(2026, 1, 1, tzinfo=UTC))


def test_cannibalization_detection() -> None:
    rows = [
        ContentRow("/a", "article", 800, primary_keyword="gemstone rings"),
        ContentRow("/b", "article", 700, primary_keyword="Gemstone Rings"),
        ContentRow("/c", "article", 600, primary_keyword="emerald rings"),
    ]
    groups = cannibalization_groups(rows)
    assert len(groups) == 1 and groups[0]["count"] == 2


def test_rule_judge_dimensions() -> None:
    rj = rule_judge("## H\n\n" + "word " * 400 + "[x](/x)", keyword="word", target_words=300)
    assert rj.scorer == "rule"
    assert set(rj.dimensions) == {"coverage", "structure", "keyword_alignment", "linking", "depth"}


def test_brief_from_serp_analysis() -> None:
    a = SerpAnalysis(query="how to clean gemstone rings", top_domains=["gia.edu", "jewelry.com"],
                     feature_types=["people_also_ask"], questions=["Can I use vinegar?"],
                     entities=[("warm water", 0.5), ("mild soap", 0.4)], common_topics=["warm water", "mild soap"])
    brief = build_brief("how to clean gemstone rings", a, serp_run_id="run-1", competitor_avg_words=1200)
    assert brief.target_word_count == 1200
    assert "Warm Water" in brief.suggested_headings
    assert brief.questions_to_answer == ["Can I use vinegar?"]
    assert brief.evidence_serp_run_id == "run-1"
