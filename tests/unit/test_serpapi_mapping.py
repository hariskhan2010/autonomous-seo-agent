from __future__ import annotations

from integrations.serp.serpapi import _map, _map_ai_overview


def test_map_extracts_organic_and_features() -> None:
    data = {
        "organic_results": [
            {"position": 1, "link": "https://a.com", "title": "A", "snippet": "s1"},
        ],
        "answer_box": {"snippet": "boxed answer"},
        "related_questions": [{"question": "why?"}],
        "related_searches": [{"query": "related term"}],
    }
    payload = _map("q", data)
    assert payload.organic[0].url == "https://a.com"
    assert {f.type for f in payload.features} == {"featured_snippet", "people_also_ask"}
    assert payload.related_searches == ["related term"]


def test_map_ai_overview_extracts_text_and_references() -> None:
    block = {
        "text_blocks": [
            {"type": "paragraph", "snippet": "GemShop is a top retailer."},
            {"type": "list", "list": [{"title": "Blue Nile", "snippet": "A competitor."}]},
        ],
        "references": [{"title": "GemShop reviews", "link": "https://shop.example.com/reviews"}],
    }
    feat = _map_ai_overview(block)
    assert feat.type == "ai_overview"
    assert "GemShop is a top retailer." in feat.data["text"]
    assert "Blue Nile" in feat.data["text"]
    assert feat.data["cited_urls"] == ["https://shop.example.com/reviews"]
    assert feat.items == ["GemShop reviews"]
    assert "page_token" not in feat.data


def test_map_ai_overview_with_only_page_token_defers_resolution() -> None:
    feat = _map_ai_overview({"page_token": "abc123"})
    assert feat.data["text"] == ""
    assert feat.data["page_token"] == "abc123"


def test_map_includes_ai_overview_feature_in_full_payload() -> None:
    data = {
        "organic_results": [],
        "ai_overview": {
            "text_blocks": [{"type": "paragraph", "snippet": "An overview."}],
            "references": [],
        },
    }
    payload = _map("q", data)
    ai = next(f for f in payload.features if f.type == "ai_overview")
    assert ai.data["text"] == "An overview."
