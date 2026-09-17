from __future__ import annotations

from seo_core.geo import audit_machine_readability
from seo_core.geo.machine_readability import check_ai_crawler_access, check_llms_txt


def test_no_robots_means_all_ai_crawlers_allowed() -> None:
    access = check_ai_crawler_access(None)
    assert all(access.values())


def test_robots_blocking_gptbot_is_detected() -> None:
    robots = "User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    access = check_ai_crawler_access(robots)
    assert access["GPTBot"] is False
    assert access["ClaudeBot"] is True


def test_llms_txt_well_formed() -> None:
    text = "# GemShop\n\n## Products\n- [Rings](https://shop.example.com/rings)\n"
    present, well_formed = check_llms_txt(text)
    assert present is True
    assert well_formed is True


def test_llms_txt_missing() -> None:
    present, well_formed = check_llms_txt(None)
    assert present is False
    assert well_formed is None


def test_audit_flags_missing_organization_schema_and_llms_txt() -> None:
    report = audit_machine_readability(brand="GemShop", robots_text=None, schema_blocks=[])
    assert report.organization_schema_present is False
    assert "no_organization_schema" in report.issues
    assert "no_llms_txt" in report.issues
    assert report.blocked_crawlers == []


def test_audit_passes_with_matching_organization_schema() -> None:
    schema = [{
        "@type": "Organization", "name": "GemShop",
        "sameAs": ["https://twitter.com/gemshop", "https://en.wikipedia.org/wiki/GemShop"],
    }]
    report = audit_machine_readability(
        brand="GemShop", robots_text="User-agent: *\nAllow: /\n", schema_blocks=schema,
        llms_txt_text="# GemShop\n- [Home](https://shop.example.com)\n",
    )
    assert report.organization_schema_present is True
    assert report.organization_name_match is True
    assert report.same_as_present is True
    assert report.llms_txt_present is True
    assert report.llms_txt_well_formed is True
    assert report.issues == []


def test_organization_name_mismatch_is_flagged() -> None:
    schema = [{"@type": "Organization", "name": "Some Other Brand", "sameAs": ["https://x.com/x"]}]
    report = audit_machine_readability(brand="GemShop", schema_blocks=schema)
    assert report.organization_name_match is False
    assert "organization_name_mismatch" in report.issues
