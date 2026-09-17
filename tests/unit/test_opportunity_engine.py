from __future__ import annotations

from opportunity_engine import bucket, detect_from_content, detect_from_issues, priority_score


def test_priority_formula_and_buckets() -> None:
    hi = priority_score(business_impact=0.9, seo_impact=0.9, confidence=0.95, feasibility=0.9, risk=0.15)
    lo = priority_score(business_impact=0.2, seo_impact=0.3, confidence=0.5, feasibility=0.4, risk=0.5)
    assert hi > lo
    assert bucket(hi) in ("P0", "P1")
    assert bucket(lo) == "P3"


def test_detect_from_issues_maps_and_keys() -> None:
    issues = [
        {"id": "e1", "check_code": "noindex_on_indexable", "severity": "high",
         "title": "noindex", "url": "https://x.com/a", "url_pattern": None, "fix": "remove noindex"},
        {"id": "e2", "check_code": "img_missing_alt", "severity": "low",
         "title": "alt", "url": "https://x.com/b", "url_pattern": None, "fix": "add alt"},
        {"id": "e3", "check_code": "not_in_catalog", "severity": "low",
         "title": "x", "url": "https://x.com/c", "url_pattern": None, "fix": None},
    ]
    found = detect_from_issues(issues)
    assert len(found) == 2  # unmapped code skipped
    noindex = next(d for d in found if d.type == "fix_technical_issue" and "a" in (d.url or ""))
    assert noindex.action_class == "LOW_RISK_WRITE"
    assert noindex.priority in ("P0", "P1")
    assert noindex.evidence_issue_ids == ["e1"]
    # idempotent key is stable
    assert detect_from_issues(issues)[0].normalized_key == found[0].normalized_key


def test_detect_from_content() -> None:
    groups = [{"keyword": "gemstone rings", "urls": ["/a", "/b"], "count": 2}]
    found = detect_from_content(groups, flags_by_url={"/c": ["thin"], "/d": []})
    types = {d.type for d in found}
    assert "consolidate_cannibalization" in types
    assert "improve_thin_content" in types
    assert all(d.action_class == "HIGH_RISK_WRITE" for d in found)
