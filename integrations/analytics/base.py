"""Metrics provider abstraction (A-TO-Z-PLAN.md §Phase 9, §20).

GSC / GA4 adapters map their API rows → `MetricRow`. `FakeMetricsProvider` powers offline dev
and the anomaly / experiment tests."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from common.settings import settings


@dataclass
class MetricRow:
    metric: str
    date: dt.date
    value: float
    scope: str = "site"
    scope_ref: str = "*"
    source: str = "gsc"


@runtime_checkable
class MetricsProvider(Protocol):
    name: str

    def fetch(self, *, start: dt.date, end: dt.date, metrics: list[str]) -> list[MetricRow]: ...


def get_metrics_provider(
    kind: str = "gsc", *, site_url: str | None = None, property_id: str | None = None,
    refresh_token: str | None = None,
) -> MetricsProvider:
    """`refresh_token` is per-tenant/per-property (a connected GSC site or GA4 property), unlike
    the app-wide LLM/SERP keys — so it's a parameter here, not a `Settings` field. Storage is
    `db.models.credential.OAuthCredential` (encrypted, per-project) — `apps/worker/worker/jobs/
    analytics.py::ingest` resolves it automatically from there when the caller doesn't pass one
    explicitly, via a real Google OAuth consent flow (`apps/api/app/routers/oauth.py`)."""
    if not settings.google_oauth_client_id:
        raise RuntimeError("no analytics provider configured (set GOOGLE_OAUTH_CLIENT_ID + connect)")
    if not refresh_token:
        raise RuntimeError(
            f"{kind} needs a connected property's OAuth refresh token — connect one via "
            "POST /v1/projects/{project_id}/oauth/google/start, or pass refresh_token explicitly"
        )
    if kind == "gsc":
        from integrations.analytics.gsc import GscProvider

        if not site_url:
            raise ValueError("gsc requires site_url")
        return GscProvider(site_url=site_url, refresh_token=refresh_token)
    if kind == "ga4":
        from integrations.analytics.ga4 import Ga4Provider

        if not property_id:
            raise ValueError("ga4 requires property_id")
        return Ga4Provider(property_id=property_id, refresh_token=refresh_token)
    raise ValueError(f"no metrics provider for {kind!r}")
