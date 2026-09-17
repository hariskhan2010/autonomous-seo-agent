"""Crawler-accuracy golden test (A-TO-Z-PLAN.md §Phase 2 — first eval dataset).

Parses a fixture page with a known, hand-checked structure. Field-level accuracy."""

from __future__ import annotations

from pathlib import Path

import pytest

from seo_core.crawl.parser import parse_html

FIXTURE = Path(__file__).parents[1] / "eval" / "golden" / "fixture_site" / "page.html"
URL = "https://shop.example.com/guides/gemstone-rings"


@pytest.fixture(scope="module")
def parsed():
    return parse_html(FIXTURE.read_text(encoding="utf-8"), url=URL, final_url=URL, http_status=200)


def test_meta_fields(parsed) -> None:
    assert parsed.title == "Gemstone Rings Buying Guide"
    assert parsed.meta_description.startswith("How to choose a gemstone ring")
    assert parsed.robots_meta == "index, follow"
    assert parsed.canonical == "https://shop.example.com/guides/gemstone-rings"


def test_headings(parsed) -> None:
    assert parsed.h1 == "Gemstone Rings Buying Guide"
    assert parsed.headings["h2"] == ["Choosing a stone", "Certification"]


def test_links_are_classified_and_deduped(parsed) -> None:
    # /guides/emeralds and its #origin variant collapse to one internal link
    assert parsed.internal_links == ["https://shop.example.com/guides/emeralds"]
    assert parsed.external_links == ["https://gia.edu/"]
    # mailto: is excluded entirely


def test_images_and_missing_alt(parsed) -> None:
    assert len(parsed.images) == 2
    alts = {i["src"].rsplit("/", 1)[-1]: i["alt"] for i in parsed.images}
    assert alts["ring.jpg"] == "A sapphire ring"
    assert alts["band.jpg"] == ""  # the technical engine flags this later


def test_schema_and_hreflang(parsed) -> None:
    assert parsed.schema_blocks[0]["@type"] == "Article"
    assert parsed.hreflang[0]["hreflang"] == "en-gb"


def test_word_count_nonzero(parsed) -> None:
    assert parsed.word_count > 20
