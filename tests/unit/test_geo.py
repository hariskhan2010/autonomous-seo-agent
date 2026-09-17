from __future__ import annotations

from integrations.ai_providers.fake import FakeAiProvider

from seo_core.geo import parse_citations, visibility_score


def _cit(text: str):
    return parse_citations(
        text, brand="GemShop", own_domain="shop.example.com",
        competitor_names=["Blue Nile", "GemSelect"],
        competitor_domains=["bluenile.com", "gemselect.com"],
    )


def test_parse_brand_and_competitors_and_own_url() -> None:
    ans = FakeAiProvider().ask("what are the best gemstone rings").text
    c = _cit(ans)
    assert c.brand_mentioned is True
    assert c.brand_position is not None
    assert "Blue Nile" in c.competitors_mentioned
    assert c.own_url_cited is True
    assert c.sentiment == "positive"


def test_no_brand_mention() -> None:
    c = _cit("Reputable sellers include Blue Nile and GemSelect.")
    assert c.brand_mentioned is False
    assert set(c.competitors_mentioned) >= {"Blue Nile", "GemSelect"}
    assert c.own_url_cited is False


def test_visibility_score_rewards_mentions_and_citations() -> None:
    strong = visibility_score([_cit(FakeAiProvider().ask("best gemstone rings").text)] * 5)
    weak = visibility_score([_cit("Try Blue Nile or GemSelect.")] * 5)
    assert strong.score > weak.score
    assert strong.brand_mention_rate == 1.0
    assert weak.brand_mention_rate == 0.0
    assert 0 <= strong.score <= 100
