"""Core Web Vitals evaluation (A-TO-Z-PLAN.md §Phase 3 — deterministic thresholds, §V).

Google's published CWV thresholds: `good` / `needs_improvement` / `poor` per metric. Only `poor`
raises a `Finding` — `seo_issues` tracks things worth fixing, not a full performance dashboard.
Field data (CrUX, real users) and lab data (Lighthouse/PSI, synthetic) are both accepted; a
`VitalsMetrics.source` tag says which, since they can legitimately disagree."""

from __future__ import annotations

from dataclasses import dataclass

from seo_core.technical.catalog import CATALOG
from seo_core.technical.models import Finding

# (good_max, needs_improvement_max) in each metric's native unit — above the second is "poor".
_THRESHOLDS: dict[str, tuple[float, float]] = {
    "lcp_ms": (2500, 4000),
    "inp_ms": (200, 500),
    "cls": (0.1, 0.25),
    "ttfb_ms": (800, 1800),
}

_CHECK_CODE = {
    "lcp_ms": "cwv_lcp_poor", "inp_ms": "cwv_inp_poor",
    "cls": "cwv_cls_poor", "ttfb_ms": "cwv_ttfb_poor",
}


@dataclass
class VitalsMetrics:
    url: str
    strategy: str = "mobile"       # "mobile" | "desktop"
    source: str = "field"          # "field" (CrUX) | "lab" (Lighthouse/PSI)
    lcp_ms: float | None = None
    inp_ms: float | None = None
    cls: float | None = None
    ttfb_ms: float | None = None


def rate(value: float | None, metric: str) -> str | None:
    """`None` if there's no reading; else "good" / "needs_improvement" / "poor"."""
    if value is None:
        return None
    good_max, ni_max = _THRESHOLDS[metric]
    if value <= good_max:
        return "good"
    if value <= ni_max:
        return "needs_improvement"
    return "poor"


def evaluate_vitals(metrics: VitalsMetrics) -> list[Finding]:
    findings: list[Finding] = []
    for metric, code in _CHECK_CODE.items():
        value = getattr(metrics, metric)
        if rate(value, metric) != "poor":
            continue
        c = CATALOG[code]
        findings.append(Finding(
            check_code=code, category=c.category, severity=c.severity, title=c.title, fix=c.fix,
            url=metrics.url,
            detail={"value": value, "strategy": metrics.strategy, "source": metrics.source},
        ))
    return findings
