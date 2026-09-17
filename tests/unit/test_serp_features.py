from __future__ import annotations

from integrations.serp.fake import FakeSerpProvider

from seo_core.serp import analyze_serp


def test_analyze_fixture_serp() -> None:
    payload = FakeSerpProvider().search("how to clean gemstone rings")
    a = analyze_serp(
        payload, own_domain="shop.example.com", competitor_domains=["jewelry.com"]
    )

    assert a.top_domains[0] == "gia.edu"
    assert "people_also_ask" in a.feature_types
    assert "featured_snippet" in a.feature_types
    assert a.own_position == 3
    assert a.competitor_positions.get("jewelry.com") == 2
    assert any("vinegar" in q.lower() for q in a.questions)
    assert a.common_topics  # entities mined from titles + snippets


def test_content_gap_flags_uncovered_topics() -> None:
    payload = FakeSerpProvider().search("how to clean gemstone rings")
    thin_page = "Buy our gemstone rings. Free shipping."
    a = analyze_serp(payload, page_text=thin_page)
    assert a.content_gap  # the ranking pages cover "warm water", "mild soap" etc. — the page doesn't


def test_unknown_query_still_analyzes() -> None:
    payload = FakeSerpProvider().search("obscure long tail query xyz")
    a = analyze_serp(payload)
    assert len(a.top_domains) >= 1
    assert a.feature_types == []
