"""SERP provider abstraction (A-TO-Z-PLAN.md §Phase 4, §51).

One interface; adapters map raw provider JSON → `seo_core.serp.SerpPayload`. Selection is by
config with a retry/fallback order (SerpAPI → DataForSEO). Tests use `FakeSerpProvider`."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from common.settings import settings
from seo_core.serp.models import SerpPayload


@runtime_checkable
class SerpProvider(Protocol):
    name: str

    def search(self, query: str, *, locale: str = "en-US", device: str = "desktop",
               num: int = 10) -> SerpPayload: ...


def get_provider(preferred: str | None = None) -> SerpProvider:
    order = [preferred] if preferred else ["serpapi", "dataforseo"]
    for name in order:
        if name == "serpapi" and settings.serpapi_api_key:
            from integrations.serp.serpapi import SerpApiProvider

            return SerpApiProvider()
        if name == "dataforseo" and settings.dataforseo_login and settings.dataforseo_password:
            from integrations.serp.dataforseo import DataForSeoProvider

            return DataForSeoProvider()
    raise RuntimeError("no SERP provider configured (set SERPAPI_API_KEY or DATAFORSEO_*)")
