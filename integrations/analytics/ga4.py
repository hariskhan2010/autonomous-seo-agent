"""GA4 Data API adapter (A-TO-Z-PLAN.md §Phase 9). Same per-property refresh-token shape as
`GscProvider` — see `get_metrics_provider`'s docstring for why it isn't a `Settings` field."""

from __future__ import annotations

import datetime as dt
from typing import Any

import httpx
from integrations.analytics.base import MetricRow

from common.settings import settings

_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105
_API_BASE = "https://analyticsdata.googleapis.com/v1beta"

_METRIC_MAP = {
    "organic_sessions": "sessions", "conversions": "conversions", "revenue": "totalRevenue",
    "users": "totalUsers", "bounce_rate": "bounceRate",
}


def _access_token(refresh_token: str) -> str:
    resp = httpx.post(
        _TOKEN_ENDPOINT,
        data={"client_id": settings.google_oauth_client_id,
              "client_secret": settings.google_oauth_client_secret,
              "refresh_token": refresh_token, "grant_type": "refresh_token"},
        timeout=30,
    )
    resp.raise_for_status()
    return str(resp.json()["access_token"])


def _map(data: dict[str, Any], ga4_metrics: dict[str, str]) -> list[MetricRow]:
    by_ga4_name = {v: k for k, v in ga4_metrics.items()}
    metric_names = [h["name"] for h in data.get("metricHeaders", [])]
    out: list[MetricRow] = []
    for row in data.get("rows", []):
        date_str = row["dimensionValues"][0]["value"]  # "YYYYMMDD"
        date = dt.date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
        for i, mv in enumerate(row.get("metricValues", [])):
            if i >= len(metric_names):
                break
            our_name = by_ga4_name.get(metric_names[i])
            if our_name is not None:
                out.append(MetricRow(metric=our_name, date=date, value=float(mv["value"]),
                                     source="ga4"))
    return out


class Ga4Provider:
    name = "ga4"

    def __init__(self, *, property_id: str, refresh_token: str) -> None:
        self.property_id = property_id
        self._refresh_token = refresh_token

    def fetch(self, *, start: dt.date, end: dt.date, metrics: list[str]) -> list[MetricRow]:
        ga4_metrics = {m: _METRIC_MAP[m] for m in metrics if m in _METRIC_MAP}
        if not ga4_metrics:
            return []
        token = _access_token(self._refresh_token)
        resp = httpx.post(
            f"{_API_BASE}/properties/{self.property_id}:runReport",
            headers={"Authorization": f"Bearer {token}"},
            json={"dateRanges": [{"startDate": start.isoformat(), "endDate": end.isoformat()}],
                  "dimensions": [{"name": "date"}],
                  "metrics": [{"name": v} for v in ga4_metrics.values()]},
            timeout=45,
        )
        resp.raise_for_status()
        return _map(resp.json(), ga4_metrics)
