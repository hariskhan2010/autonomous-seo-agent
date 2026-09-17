"""Anomaly detection (A-TO-Z-PLAN.md §21, §V — deterministic).

Rolling-baseline z-score with a seasonality-aware baseline (same weekday over a trailing window,
not raw day-over-day). Flags drops/spikes past a z threshold AND a minimum % change, so noise
inside the variance band is not reported."""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass


@dataclass
class Point:
    date: dt.date
    value: float


@dataclass
class AnomalyHit:
    metric: str
    date: dt.date
    direction: str          # drop / spike
    observed: float
    baseline: float
    magnitude_pct: float
    z_score: float


def _baseline_points(series: list[Point], target: Point, *, window_days: int) -> list[float]:
    cutoff = target.date - dt.timedelta(days=window_days)
    same_weekday = [
        p.value for p in series
        if cutoff <= p.date < target.date and p.date.weekday() == target.date.weekday()
    ]
    if len(same_weekday) >= 3:
        return same_weekday
    return [p.value for p in series if cutoff <= p.date < target.date]


def detect_anomalies(
    metric: str,
    series: list[Point],
    *,
    window_days: int = 28,
    z_threshold: float = 2.5,
    min_pct: float = 15.0,
) -> list[AnomalyHit]:
    series = sorted(series, key=lambda p: p.date)
    hits: list[AnomalyHit] = []
    for i, point in enumerate(series):
        if i < 4:
            continue
        base = _baseline_points(series, point, window_days=window_days)
        if len(base) < 3:
            continue
        mean = statistics.fmean(base)
        stdev = statistics.pstdev(base) or 1e-9
        z = (point.value - mean) / stdev
        pct = ((point.value - mean) / mean * 100) if mean else 0.0
        if abs(z) >= z_threshold and abs(pct) >= min_pct:
            hits.append(AnomalyHit(
                metric=metric, date=point.date,
                direction="drop" if point.value < mean else "spike",
                observed=round(point.value, 4), baseline=round(mean, 4),
                magnitude_pct=round(pct, 2), z_score=round(z, 3),
            ))
    return hits
