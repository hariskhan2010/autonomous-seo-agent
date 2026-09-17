from __future__ import annotations

import pytest
from integrations.pagespeed import FakeVitalsProvider, get_vitals_provider
from integrations.pagespeed.psi import PageSpeedInsightsProvider, _map


def test_fake_provider_returns_one_reading() -> None:
    provider = get_vitals_provider("fake")
    assert isinstance(provider, FakeVitalsProvider)
    readings = provider.fetch("https://x.com", strategy="mobile")
    assert len(readings) == 1
    assert readings[0].strategy == "mobile"


def test_map_extracts_field_and_lab_metrics() -> None:
    data = {
        "loadingExperience": {
            "metrics": {
                "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 3000},
                "INTERACTION_TO_NEXT_PAINT": {"percentile": 180},
                "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 12},
                "EXPERIMENTAL_TIME_TO_FIRST_BYTE": {"percentile": 700},
            }
        },
        "lighthouseResult": {
            "audits": {
                "largest-contentful-paint": {"numericValue": 2800},
                "cumulative-layout-shift": {"numericValue": 0.08},
                "server-response-time": {"numericValue": 650},
            }
        },
    }
    readings = _map("https://x.com/page", "mobile", data)
    field = next(r for r in readings if r.source == "field")
    lab = next(r for r in readings if r.source == "lab")

    assert field.lcp_ms == 3000
    assert field.inp_ms == 180
    assert field.cls == 0.12  # 12 / 100
    assert field.ttfb_ms == 700

    assert lab.lcp_ms == 2800
    assert lab.cls == 0.08
    assert lab.ttfb_ms == 650
    assert lab.inp_ms is None  # no reliable single-load lab proxy for INP


def test_map_handles_missing_field_data() -> None:
    data = {"lighthouseResult": {"audits": {"largest-contentful-paint": {"numericValue": 1200}}}}
    readings = _map("https://x.com/page", "desktop", data)
    assert len(readings) == 1
    assert readings[0].source == "lab"
    assert readings[0].strategy == "desktop"


def test_missing_key_raises_at_fetch_time(monkeypatch: pytest.MonkeyPatch) -> None:
    from common.settings import settings

    monkeypatch.setattr(settings, "pagespeed_api_key", "")
    with pytest.raises(RuntimeError, match="PAGESPEED_API_KEY"):
        PageSpeedInsightsProvider().fetch("https://x.com")
