"""Google PageSpeed Insights v5 adapter (A-TO-Z-PLAN.md §Phase 3). Lazy — no key needed to
import. One call returns `loadingExperience` (field data, real Chrome users on this exact URL —
i.e. CrUX) and `lighthouseResult` (lab data, synthetic) side by side."""

from __future__ import annotations

from typing import Any

import httpx

from common.settings import settings
from seo_core.technical.vitals import VitalsMetrics

_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


class PageSpeedInsightsProvider:
    name = "pagespeed"

    def fetch(self, url: str, *, strategy: str = "mobile") -> list[VitalsMetrics]:
        if not settings.pagespeed_api_key:
            raise RuntimeError("PAGESPEED_API_KEY not configured — see NEEDED-KEYS.md")
        data = httpx.get(
            _ENDPOINT,
            params={"url": url, "strategy": strategy, "category": "PERFORMANCE",
                    "key": settings.pagespeed_api_key},
            timeout=45,
        ).json()
        if "error" in data:
            raise RuntimeError(f"PageSpeed Insights: {data['error'].get('message', data['error'])}")
        return _map(url, strategy, data)


def _percentile(metric: dict[str, Any] | None, *, scale: float = 1.0) -> float | None:
    if not metric or metric.get("percentile") is None:
        return None
    return float(metric["percentile"]) * scale


def _audit_value(audit: dict[str, Any] | None) -> float | None:
    if not audit or audit.get("numericValue") is None:
        return None
    return float(audit["numericValue"])


def _map(url: str, strategy: str, data: dict[str, Any]) -> list[VitalsMetrics]:
    out: list[VitalsMetrics] = []

    field = (data.get("loadingExperience") or {}).get("metrics") or {}
    if field:
        out.append(VitalsMetrics(
            url=url, strategy=strategy, source="field",
            lcp_ms=_percentile(field.get("LARGEST_CONTENTFUL_PAINT_MS")),
            inp_ms=_percentile(field.get("INTERACTION_TO_NEXT_PAINT")),
            # CrUX reports CLS*100 as an integer percentile — see Google's CrUX API docs.
            cls=_percentile(field.get("CUMULATIVE_LAYOUT_SHIFT_SCORE"), scale=0.01),
            ttfb_ms=_percentile(field.get("EXPERIMENTAL_TIME_TO_FIRST_BYTE")),
        ))

    audits = (data.get("lighthouseResult") or {}).get("audits") or {}
    if audits:
        out.append(VitalsMetrics(
            url=url, strategy=strategy, source="lab",
            lcp_ms=_audit_value(audits.get("largest-contentful-paint")),
            cls=_audit_value(audits.get("cumulative-layout-shift")),
            ttfb_ms=_audit_value(audits.get("server-response-time")),
            # INP has no reliable single-page-load lab proxy; only CrUX (field) reports it.
        ))
    return out
