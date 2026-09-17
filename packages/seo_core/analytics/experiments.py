"""Experiment evaluation (A-TO-Z-PLAN.md §21, §34–35 — deterministic).

Enforces the methodology: baseline vs treatment window comparison, a control arm where present,
a measurement-window minimum, and confounder accounting (algorithm updates, seasonality, tracking
changes). **A result inside the noise band or overlapping a confounder is `inconclusive`, never
`success`.** No causal language without a control arm."""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass, field

# known Google core-update windows (extend from a maintained list in prod)
_ALGO_WINDOWS: list[tuple[dt.date, dt.date, str]] = [
    (dt.date(2026, 3, 5), dt.date(2026, 3, 20), "March 2026 core update"),
    (dt.date(2026, 6, 10), dt.date(2026, 6, 25), "June 2026 core update"),
]

_MIN_WINDOW_DAYS = {"position": 14, "clicks": 28, "impressions": 21, "organic_sessions": 28,
                    "conversions": 42, "revenue": 42}


@dataclass
class ExperimentSpec:
    primary_metric: str
    baseline: list[float]
    treatment: list[float]
    treatment_start: dt.date
    measurement_window_days: int
    control_baseline: list[float] = field(default_factory=list)
    control_treatment: list[float] = field(default_factory=list)
    tracking_changed: bool = False


@dataclass
class ExperimentResult:
    verdict: str            # success / neutral / regression / inconclusive
    confidence: float
    effect_pct: float
    control_adjusted_pct: float | None
    confounders: list[str]
    methodology: dict[str, object]
    causal_language_allowed: bool


def _overlapping_algo_updates(start: dt.date, window_days: int) -> list[str]:
    end = start + dt.timedelta(days=window_days)
    return [name for (a, b, name) in _ALGO_WINDOWS if a <= end and b >= start]


def evaluate_experiment(spec: ExperimentSpec) -> ExperimentResult:
    confounders: list[str] = []
    if spec.tracking_changed:
        confounders.append("GSC/GA tracking or property changed during the window")
    confounders += _overlapping_algo_updates(spec.treatment_start, spec.measurement_window_days)

    min_days = _MIN_WINDOW_DAYS.get(spec.primary_metric, 21)
    window_ok = spec.measurement_window_days >= min_days

    b_mean = statistics.fmean(spec.baseline) if spec.baseline else 0.0
    t_mean = statistics.fmean(spec.treatment) if spec.treatment else 0.0
    effect_pct = ((t_mean - b_mean) / b_mean * 100) if b_mean else 0.0
    # lower position is better — flip sign so "improvement" is always positive
    if spec.primary_metric == "position":
        effect_pct = -effect_pct

    noise_band = 0.0
    if len(spec.baseline) >= 3:
        noise_band = statistics.pstdev(spec.baseline) / b_mean * 100 if b_mean else 0.0

    has_control = bool(spec.control_baseline and spec.control_treatment)
    control_adj: float | None = None
    if has_control:
        cb = statistics.fmean(spec.control_baseline)
        ct = statistics.fmean(spec.control_treatment)
        control_pct = ((ct - cb) / cb * 100) if cb else 0.0
        if spec.primary_metric == "position":
            control_pct = -control_pct
        control_adj = effect_pct - control_pct  # difference-in-differences

    signal = control_adj if control_adj is not None else effect_pct

    if confounders or not window_ok:
        verdict = "inconclusive"
        conf = 0.3
    elif abs(signal) <= max(noise_band, 3.0):
        verdict = "neutral"
        conf = 0.6
    elif signal > 0:
        verdict = "success"
        conf = 0.8 if has_control else 0.6
    else:
        verdict = "regression"
        conf = 0.8 if has_control else 0.6

    return ExperimentResult(
        verdict=verdict,
        confidence=conf,
        effect_pct=round(effect_pct, 2),
        control_adjusted_pct=round(control_adj, 2) if control_adj is not None else None,
        confounders=confounders,
        methodology={
            "window_ok": window_ok, "min_window_days": min_days,
            "noise_band_pct": round(noise_band, 2), "has_control": has_control,
            "method": "difference-in-differences" if has_control else "before/after",
        },
        causal_language_allowed=has_control and verdict in ("success", "regression") and not confounders,
    )
