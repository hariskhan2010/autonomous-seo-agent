from __future__ import annotations

from reporting import executive_report, technical_report


def test_executive_report_renders_all_sections() -> None:
    r = executive_report(
        project_name="Acme",
        metrics={"clicks": (1200.0, 1000.0), "position": (6.5, 8.0)},
        open_opportunities=[
            {"priority": "P0", "type": "fix_canonical", "title": "Canonical wrong", "score": 65,
             "action_class": "LOW_RISK_WRITE"},
            {"priority": "P3", "type": "add_schema", "title": "No schema", "score": 8},
        ],
        recent_changes=[{"target": "content/a.md", "state": "verified", "verified": True,
                         "applied_at": "2026-09-01T00:00:00"}],
        ai_visibility={"openrouter": 42.0, "gemini": 55.5},
    )
    assert "Executive SEO Report — Acme" in r.markdown
    assert "▲ +20.0%" in r.markdown          # clicks up 20%
    assert "Canonical wrong" in r.markdown
    assert "No schema" not in r.markdown     # P3 excluded from priority table
    assert "gemini" in r.markdown
    assert r.sections == ["performance", "opportunities", "changes", "ai_visibility"]


def test_technical_report_groups_by_severity() -> None:
    r = technical_report(
        project_name="Acme",
        issues_by_severity={
            "critical": [{"check_code": "status_5xx", "url": "https://x/a", "fix": "fix server"}],
            "low": [{"check_code": "img_missing_alt", "url": "https://x/b", "fix": "add alt"}],
        },
    )
    assert "2 open issues" in r.markdown
    assert "## Critical (1)" in r.markdown
    assert "status_5xx" in r.markdown
