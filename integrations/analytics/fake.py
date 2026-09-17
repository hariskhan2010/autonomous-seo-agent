"""Deterministic fake metrics provider — a stable seasonal series with an optional injected
drop, for offline dev + anomaly/experiment tests."""

from __future__ import annotations

import datetime as dt
import math

from integrations.analytics.base import MetricRow

_BASE = {"clicks": 1000.0, "impressions": 40000.0, "position": 8.0, "ctr": 0.025,
         "organic_sessions": 1500.0, "conversions": 30.0, "revenue": 3000.0}


class FakeMetricsProvider:
    name = "fake"

    def __init__(self, *, drop_on: dt.date | None = None, drop_pct: float = 0.35) -> None:
        self.drop_on = drop_on
        self.drop_pct = drop_pct

    def fetch(self, *, start: dt.date, end: dt.date, metrics: list[str]) -> list[MetricRow]:
        rows: list[MetricRow] = []
        day = start
        while day <= end:
            weekday_factor = 0.85 if day.weekday() >= 5 else 1.0
            wobble = 1.0 + 0.03 * math.sin(day.toordinal())
            for m in metrics:
                base = _BASE.get(m, 100.0) * weekday_factor * wobble
                if self.drop_on and day >= self.drop_on and m != "position":
                    base *= (1 - self.drop_pct)
                if self.drop_on and day >= self.drop_on and m == "position":
                    base += 4.0  # rankings got worse
                rows.append(MetricRow(metric=m, date=day, value=round(base, 4), source="fake"))
            day += dt.timedelta(days=1)
        return rows
