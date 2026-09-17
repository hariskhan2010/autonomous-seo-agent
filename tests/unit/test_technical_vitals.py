from __future__ import annotations

from seo_core.technical.vitals import VitalsMetrics, evaluate_vitals, rate


def test_rate_thresholds() -> None:
    assert rate(2000, "lcp_ms") == "good"
    assert rate(3000, "lcp_ms") == "needs_improvement"
    assert rate(5000, "lcp_ms") == "poor"
    assert rate(None, "lcp_ms") is None


def test_all_good_metrics_produce_no_findings() -> None:
    m = VitalsMetrics(url="https://x.com/a", lcp_ms=2000, inp_ms=150, cls=0.05, ttfb_ms=500)
    assert evaluate_vitals(m) == []


def test_poor_lcp_and_cls_produce_findings_only_for_those() -> None:
    m = VitalsMetrics(url="https://x.com/a", lcp_ms=5000, inp_ms=150, cls=0.4, ttfb_ms=500)
    findings = evaluate_vitals(m)
    codes = {f.check_code for f in findings}
    assert codes == {"cwv_lcp_poor", "cwv_cls_poor"}
    lcp = next(f for f in findings if f.check_code == "cwv_lcp_poor")
    assert lcp.detail["value"] == 5000
    assert lcp.url == "https://x.com/a"


def test_missing_metric_is_not_flagged() -> None:
    m = VitalsMetrics(url="https://x.com/a")  # nothing measured
    assert evaluate_vitals(m) == []
