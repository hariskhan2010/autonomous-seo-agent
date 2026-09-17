"""Ported + expanded from seo-agent/tests/test_validator.py + test_utils.py."""

from __future__ import annotations

import pytest

from seo_core import confidence, validation


def test_domain_valid() -> None:
    assert validation.domain("asiangemstone.vercel.app") == "asiangemstone.vercel.app"


def test_domain_invalid() -> None:
    with pytest.raises(validation.ValidationError):
        validation.domain("not a domain!!")


def test_keyword_rejects_empty() -> None:
    with pytest.raises(validation.ValidationError):
        validation.keyword("   ")


def test_date_range_max_days() -> None:
    with pytest.raises(validation.ValidationError):
        validation.date_range("2026-01-01", "2026-12-31", max_days=100)


def test_date_range_ok() -> None:
    assert validation.date_range("2026-01-01", "2026-01-10") == ("2026-01-01", "2026-01-10")


def test_non_empty_rejects_empty() -> None:
    with pytest.raises(validation.ValidationError):
        validation.non_empty([])


def test_score_bounds() -> None:
    validation.score(0)
    validation.score(100)
    with pytest.raises(validation.ValidationError):
        validation.score(101)


def test_confidence_firsthand_high() -> None:
    assert confidence.score("crawl") > 0.9
    assert confidence.is_firsthand("crawl") is True


def test_confidence_unknown_low() -> None:
    assert confidence.score("made-up-source") < 0.5


def test_confidence_freshness_penalty() -> None:
    fresh = confidence.score("gsc", age_days=1)
    stale = confidence.score("gsc", age_days=400)
    assert stale < fresh


def test_confidence_label() -> None:
    assert confidence.label(0.97) == "HIGH"
    assert confidence.label(0.5) == "LOW"
