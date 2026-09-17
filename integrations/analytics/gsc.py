"""Google Search Console adapter (A-TO-Z-PLAN.md §Phase 9).

Real Search Analytics API call, given a per-property OAuth refresh token — that's a constructor
arg rather than a `Settings` field, since it's per-tenant/per-property, not a single app-wide
secret like the LLM provider keys (see `get_metrics_provider`'s docstring for why)."""

from __future__ import annotations

import datetime as dt
from typing import Any
from urllib.parse import quote

import httpx
from integrations.analytics.base import MetricRow

from common.settings import settings

_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105 - a URL, not a secret
_API_BASE = "https://www.googleapis.com/webmasters/v3"
_DIMENSION_METRICS = ("clicks", "impressions", "ctr", "position")


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


def _map(data: dict[str, Any], wanted: list[str]) -> list[MetricRow]:
    out: list[MetricRow] = []
    for row in data.get("rows", []):
        date = dt.date.fromisoformat(row["keys"][0])
        for metric in wanted:
            value = row.get(metric)
            if value is not None:
                out.append(MetricRow(metric=metric, date=date, value=float(value), source="gsc"))
    return out


class GscProvider:
    name = "gsc"

    def __init__(self, *, site_url: str, refresh_token: str) -> None:
        self.site_url = site_url
        self._refresh_token = refresh_token

    def fetch(self, *, start: dt.date, end: dt.date, metrics: list[str]) -> list[MetricRow]:
        wanted = [m for m in metrics if m in _DIMENSION_METRICS]
        if not wanted:
            return []
        token = _access_token(self._refresh_token)
        resp = httpx.post(
            f"{_API_BASE}/sites/{quote(self.site_url, safe='')}/searchAnalytics/query",
            headers={"Authorization": f"Bearer {token}"},
            json={"startDate": start.isoformat(), "endDate": end.isoformat(),
                  "dimensions": ["date"], "rowLimit": 25000},
            timeout=45,
        )
        resp.raise_for_status()
        return _map(resp.json(), wanted)
