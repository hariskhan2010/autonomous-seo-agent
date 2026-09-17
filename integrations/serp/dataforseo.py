"""DataForSEO adapter (A-TO-Z-PLAN.md §Phase 4, §51 fallback). Skeleton — wired when creds are
set. Kept minimal on purpose; SerpAPI is the primary path."""

from __future__ import annotations

import base64

import httpx

from common.settings import settings
from seo_core.serp.models import SerpFeatureRaw, SerpItem, SerpPayload

_ENDPOINT = "https://api.dataforseo.com/v3/serp/google/organic/live/advanced"


class DataForSeoProvider:
    name = "dataforseo"

    def _auth(self) -> str:
        raw = f"{settings.dataforseo_login}:{settings.dataforseo_password}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    def search(self, query: str, *, locale: str = "en-US", device: str = "desktop",
               num: int = 10) -> SerpPayload:
        lang, _, country = locale.partition("-")
        body = [{"keyword": query, "language_code": lang or "en",
                 "location_name": "United States" if (country or "us").lower() == "us" else country,
                 "device": device, "depth": num}]
        resp = httpx.post(_ENDPOINT, json=body, headers={"Authorization": self._auth()}, timeout=45)
        data = resp.json()
        items = data["tasks"][0]["result"][0]["items"]
        organic: list[SerpItem] = []
        features: list[SerpFeatureRaw] = []
        for it in items:
            if it["type"] == "organic":
                organic.append(SerpItem(position=it.get("rank_absolute", len(organic) + 1),
                                        url=it.get("url", ""), title=it.get("title", ""),
                                        snippet=it.get("description", "")))
            elif it["type"] == "people_also_ask":
                features.append(SerpFeatureRaw("people_also_ask",
                                               items=[q.get("title", "") for q in it.get("items", [])]))
        return SerpPayload(query=query, provider="dataforseo", organic=organic,
                           features=features, raw=data)
