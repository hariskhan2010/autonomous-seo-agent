"""Deterministic fake Core Web Vitals provider for offline dev + tests."""

from __future__ import annotations

from seo_core.technical.vitals import VitalsMetrics


class FakeVitalsProvider:
    name = "fake"

    def fetch(self, url: str, *, strategy: str = "mobile") -> list[VitalsMetrics]:
        return [VitalsMetrics(url=url, strategy=strategy, source="field",
                              lcp_ms=4200.0, inp_ms=150.0, cls=0.05, ttfb_ms=400.0)]
