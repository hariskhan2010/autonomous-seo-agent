"""SerpAPI adapter (A-TO-Z-PLAN.md §Phase 4). Lazy — no key needed to import."""

from __future__ import annotations

from typing import Any

import httpx

from common.settings import settings
from seo_core.serp.models import SerpFeatureRaw, SerpItem, SerpPayload

_ENDPOINT = "https://serpapi.com/search"


class SerpApiProvider:
    name = "serpapi"

    def search(self, query: str, *, locale: str = "en-US", device: str = "desktop",
               num: int = 10) -> SerpPayload:
        lang, _, country = locale.partition("-")
        params: dict[str, str | int] = {
            "engine": "google", "q": query, "num": num,
            "hl": lang or "en", "gl": (country or "us").lower(),
            "device": device, "api_key": settings.serpapi_api_key,
        }
        data = httpx.get(_ENDPOINT, params=params, timeout=30).json()
        if "error" in data:
            raise RuntimeError(f"SerpAPI: {data['error']}")
        return _map(query, data)

    def resolve_ai_overview(self, page_token: str) -> dict[str, Any]:
        """SerpAPI sometimes returns only a `page_token` for the AI Overview block; this makes
        the documented follow-up call (`engine=google_ai_overview`) to fetch the full content."""
        data = httpx.get(
            _ENDPOINT,
            params={"engine": "google_ai_overview", "page_token": page_token,
                    "api_key": settings.serpapi_api_key},
            timeout=30,
        ).json()
        if "error" in data:
            raise RuntimeError(f"SerpAPI: {data['error']}")
        return dict(data.get("ai_overview", data))


def _map_ai_overview(block: dict[str, Any]) -> SerpFeatureRaw:
    text_blocks = block.get("text_blocks") or []
    references = [r for r in (block.get("references") or []) if isinstance(r, dict)]

    def _block_text(tb: dict[str, Any]) -> str:
        if tb.get("type") == "list":
            return " ".join(
                f"{item.get('title', '')} {item.get('snippet', '')}".strip()
                for item in tb.get("list", []) if isinstance(item, dict)
            )
        return str(tb.get("snippet", ""))

    text = " ".join(_block_text(tb) for tb in text_blocks if isinstance(tb, dict)).strip()
    data: dict[str, object] = {
        "text": text,
        "references": references,
        "cited_urls": [r["link"] for r in references if r.get("link")],
    }
    if not text_blocks and block.get("page_token"):
        # Needs SerpApiProvider.resolve_ai_overview(page_token) to get the full content.
        data["page_token"] = block["page_token"]
    return SerpFeatureRaw("ai_overview", items=[r.get("title", "") for r in references], data=data)


def _map(query: str, data: dict[str, Any]) -> SerpPayload:
    organic = [
        SerpItem(position=r.get("position", i + 1), url=r.get("link", ""),
                 title=r.get("title", ""), snippet=r.get("snippet", ""))
        for i, r in enumerate(data.get("organic_results", []))
    ]
    features: list[SerpFeatureRaw] = []
    if data.get("answer_box"):
        features.append(SerpFeatureRaw("featured_snippet", data=data["answer_box"]))
    paa = data.get("related_questions") or data.get("people_also_ask") or []
    if paa:
        features.append(SerpFeatureRaw(
            "people_also_ask", items=[q.get("question", "") for q in paa]
        ))
    for key, ftype in (("inline_videos", "video"), ("inline_images", "image_pack"),
                       ("top_stories", "top_stories"), ("local_results", "local_pack"),
                       ("shopping_results", "shopping")):
        if data.get(key):
            block = data[key]
            titles = [x.get("title", "") for x in block] if isinstance(block, list) else []
            features.append(SerpFeatureRaw(ftype, items=titles))

    if data.get("ai_overview"):
        features.append(_map_ai_overview(data["ai_overview"]))
    related = [r.get("query", "") for r in data.get("related_searches", [])]
    return SerpPayload(query=query, provider="serpapi", organic=organic,
                       features=features, related_searches=related, raw=data)
