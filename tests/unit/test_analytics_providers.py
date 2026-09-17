from __future__ import annotations

import datetime as dt

import pytest
from integrations.analytics.base import get_metrics_provider
from integrations.analytics.ga4 import _map as ga4_map
from integrations.analytics.gsc import _map as gsc_map


def test_gsc_map_filters_to_wanted_metrics() -> None:
    data = {"rows": [{"keys": ["2026-01-01"], "clicks": 10, "impressions": 100, "position": 4.5}]}
    rows = gsc_map(data, ["clicks", "position"])
    metrics = {r.metric: r.value for r in rows}
    assert metrics == {"clicks": 10.0, "position": 4.5}
    assert all(r.date == dt.date(2026, 1, 1) and r.source == "gsc" for r in rows)


def test_gsc_map_skips_missing_metric_values() -> None:
    data = {"rows": [{"keys": ["2026-01-01"], "clicks": 10}]}
    rows = gsc_map(data, ["clicks", "impressions"])
    assert len(rows) == 1
    assert rows[0].metric == "clicks"


def test_ga4_map_translates_metric_names_back() -> None:
    data = {
        "metricHeaders": [{"name": "sessions"}, {"name": "totalRevenue"}],
        "rows": [{"dimensionValues": [{"value": "20260115"}],
                  "metricValues": [{"value": "42"}, {"value": "199.5"}]}],
    }
    rows = ga4_map(data, {"organic_sessions": "sessions", "revenue": "totalRevenue"})
    by_metric = {r.metric: r.value for r in rows}
    assert by_metric == {"organic_sessions": 42.0, "revenue": 199.5}
    assert all(r.date == dt.date(2026, 1, 15) and r.source == "ga4" for r in rows)


def test_get_metrics_provider_requires_oauth_client(monkeypatch: pytest.MonkeyPatch) -> None:
    from common.settings import settings

    monkeypatch.setattr(settings, "google_oauth_client_id", "")
    with pytest.raises(RuntimeError, match="GOOGLE_OAUTH_CLIENT_ID"):
        get_metrics_provider("gsc", site_url="https://x.com", refresh_token="rt")


def test_get_metrics_provider_requires_refresh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from common.settings import settings

    monkeypatch.setattr(settings, "google_oauth_client_id", "configured-client-id")
    with pytest.raises(RuntimeError, match="oauth/google/start"):
        get_metrics_provider("gsc", site_url="https://x.com")


def test_get_metrics_provider_gsc_requires_site_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from common.settings import settings

    monkeypatch.setattr(settings, "google_oauth_client_id", "configured-client-id")
    with pytest.raises(ValueError, match="site_url"):
        get_metrics_provider("gsc", refresh_token="rt")


def test_get_metrics_provider_ga4_requires_property_id(monkeypatch: pytest.MonkeyPatch) -> None:
    from common.settings import settings

    monkeypatch.setattr(settings, "google_oauth_client_id", "configured-client-id")
    with pytest.raises(ValueError, match="property_id"):
        get_metrics_provider("ga4", refresh_token="rt")
