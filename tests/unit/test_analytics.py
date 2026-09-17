from __future__ import annotations

import datetime as dt

from seo_core.analytics.anomaly import Point, detect_anomalies
from seo_core.analytics.experiments import ExperimentSpec, evaluate_experiment

UTC = dt.UTC


def _series(n: int, base: float, drop_from: int | None = None, drop: float = 0.4) -> list[Point]:
    start = dt.date(2026, 1, 1)
    out = []
    for i in range(n):
        v = base * (0.85 if (start + dt.timedelta(days=i)).weekday() >= 5 else 1.0)
        if drop_from is not None and i >= drop_from:
            v *= (1 - drop)
        out.append(Point(date=start + dt.timedelta(days=i), value=round(v, 2)))
    return out


def test_no_anomaly_on_stable_series() -> None:
    assert detect_anomalies("clicks", _series(60, 1000)) == []


def test_detects_sustained_drop() -> None:
    hits = detect_anomalies("clicks", _series(60, 1000, drop_from=45, drop=0.4))
    assert hits and all(h.direction == "drop" for h in hits)
    assert hits[0].magnitude_pct < -20


def test_ignores_small_wobble_inside_noise_band() -> None:
    hits = detect_anomalies("clicks", _series(60, 1000, drop_from=45, drop=0.05))
    assert hits == []


# ── experiment methodology ──
def test_before_after_no_control_forbids_causal_language() -> None:
    res = evaluate_experiment(ExperimentSpec(
        primary_metric="clicks", baseline=[100] * 10, treatment=[130] * 10,
        treatment_start=dt.date(2026, 1, 15), measurement_window_days=28,
    ))
    assert res.verdict == "success"
    assert res.causal_language_allowed is False  # no control arm


def test_control_arm_enables_causal_language() -> None:
    res = evaluate_experiment(ExperimentSpec(
        primary_metric="clicks", baseline=[100] * 10, treatment=[130] * 10,
        control_baseline=[100] * 10, control_treatment=[101] * 10,
        treatment_start=dt.date(2026, 1, 15), measurement_window_days=28,
    ))
    assert res.verdict == "success"
    assert res.causal_language_allowed is True
    assert res.control_adjusted_pct is not None and res.control_adjusted_pct > 20


def test_algo_update_overlap_forces_inconclusive() -> None:
    res = evaluate_experiment(ExperimentSpec(
        primary_metric="clicks", baseline=[100] * 10, treatment=[150] * 10,
        treatment_start=dt.date(2026, 3, 1), measurement_window_days=28,
    ))
    assert res.verdict == "inconclusive"
    assert any("core update" in c for c in res.confounders)


def test_short_window_is_inconclusive() -> None:
    res = evaluate_experiment(ExperimentSpec(
        primary_metric="conversions", baseline=[10] * 5, treatment=[15] * 5,
        treatment_start=dt.date(2026, 1, 15), measurement_window_days=10,
    ))
    assert res.verdict == "inconclusive"


def test_position_metric_sign_flip() -> None:
    # position 8 -> 5 is an improvement
    res = evaluate_experiment(ExperimentSpec(
        primary_metric="position", baseline=[8.0] * 20, treatment=[5.0] * 20,
        control_baseline=[8.0] * 20, control_treatment=[8.0] * 20,
        treatment_start=dt.date(2026, 1, 15), measurement_window_days=21,
    ))
    assert res.verdict == "success" and res.effect_pct > 0
