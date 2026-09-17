"""Core Web Vitals provider abstraction (A-TO-Z-PLAN.md §Phase 3).

PageSpeed Insights v5 returns both lab (Lighthouse) and field (CrUX, for that exact URL) data in
one call — a provider may return one `VitalsMetrics` per source it has data for."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from seo_core.technical.vitals import VitalsMetrics


@runtime_checkable
class VitalsProvider(Protocol):
    name: str

    def fetch(self, url: str, *, strategy: str = "mobile") -> list[VitalsMetrics]: ...
