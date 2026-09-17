"""Opportunity detectors (A-TO-Z-PLAN.md §Phase 7 — deterministic).

Each detector maps a signal (seo_issue, content flag, keyword/link gap) to a `Detected`
opportunity with an idempotent `normalized_key` and an action classification. Recommendation
*prose* is enriched by the WORKER role later; the structure comes from here."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from opportunity_engine.score import bucket, priority_score

# check_code -> (opp_type, action_class, base business/seo/feasibility/risk)
_ISSUE_MAP: dict[str, tuple[str, str, float, float, float, float]] = {
    "status_5xx":            ("fix_technical_issue", "HIGH_RISK_WRITE", 0.9, 0.9, 0.4, 0.5),
    "status_4xx":            ("fix_technical_issue", "LOW_RISK_WRITE", 0.7, 0.7, 0.6, 0.3),
    "noindex_on_indexable": ("fix_technical_issue", "LOW_RISK_WRITE", 0.8, 0.9, 0.8, 0.2),
    "canonical_not_self":   ("fix_canonical", "LOW_RISK_WRITE", 0.7, 0.8, 0.8, 0.2),
    "canonical_missing":    ("fix_canonical", "LOW_RISK_WRITE", 0.5, 0.6, 0.9, 0.15),
    "redirect_chain":       ("fix_technical_issue", "LOW_RISK_WRITE", 0.4, 0.5, 0.7, 0.25),
    "title_missing":        ("fix_technical_issue", "LOW_RISK_WRITE", 0.6, 0.7, 0.9, 0.1),
    "meta_desc_missing":    ("fix_technical_issue", "LOW_RISK_WRITE", 0.3, 0.4, 0.95, 0.1),
    "h1_missing":           ("fix_technical_issue", "LOW_RISK_WRITE", 0.4, 0.5, 0.9, 0.1),
    "schema_missing":       ("add_schema", "LOW_RISK_WRITE", 0.4, 0.5, 0.7, 0.2),
    "img_missing_alt":      ("fix_technical_issue", "LOW_RISK_WRITE", 0.2, 0.3, 0.95, 0.05),
    "broken_internal_link": ("fix_technical_issue", "LOW_RISK_WRITE", 0.5, 0.6, 0.85, 0.15),
    "orphan_page":          ("add_internal_links", "LOW_RISK_WRITE", 0.6, 0.7, 0.7, 0.2),
    "thin_content":         ("improve_thin_content", "HIGH_RISK_WRITE", 0.6, 0.7, 0.4, 0.3),
    "near_duplicate":       ("consolidate_cannibalization", "HIGH_RISK_WRITE", 0.6, 0.7, 0.4, 0.4),
    "hreflang_no_self":     ("fix_technical_issue", "LOW_RISK_WRITE", 0.5, 0.6, 0.8, 0.2),
}

_SEVERITY_CONF = {"critical": 0.95, "high": 0.9, "medium": 0.8, "low": 0.65, "info": 0.5}


@dataclass
class Detected:
    type: str
    normalized_key: str
    title: str
    url: str | None
    url_pattern: str | None
    action_class: str
    priority: str
    score: float
    inputs: dict[str, float]
    detector: str
    recommendation: str
    verification_method: str
    expected_outcome: str
    evidence_issue_ids: list[str] = field(default_factory=list)


def _key(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def detect_from_issues(issues: list[dict[str, str | None]]) -> list[Detected]:
    out: list[Detected] = []
    for issue in issues:
        code = issue.get("check_code") or ""
        mapped = _ISSUE_MAP.get(code)
        if not mapped:
            continue
        otype, action, biz, seo, feas, risk = mapped
        conf = _SEVERITY_CONF.get(issue.get("severity") or "medium", 0.8)
        score = priority_score(business_impact=biz, seo_impact=seo, confidence=conf,
                               feasibility=feas, risk=risk)
        url = issue.get("url")
        pattern = issue.get("url_pattern")
        out.append(Detected(
            type=otype,
            normalized_key=_key("issue", otype, pattern or url or "*"),
            title=f"{issue.get('title', code)}",
            url=url, url_pattern=pattern, action_class=action,
            priority=bucket(score), score=score,
            inputs={"business_impact": biz, "seo_impact": seo, "confidence": conf,
                    "feasibility": feas, "risk": risk},
            detector="issue_detector",
            recommendation=(issue.get("fix") or f"Resolve: {code}"),
            verification_method="re-fetch the live page and assert the corrected element",
            expected_outcome="issue no longer detected on the next crawl",
            evidence_issue_ids=([issue["id"]] if issue.get("id") else []),  # type: ignore[list-item]
        ))
    return out


def detect_from_content(cannibalization_groups: list[dict[str, object]], *, flags_by_url: dict[str, list[str]]) -> list[Detected]:
    out: list[Detected] = []
    for grp in cannibalization_groups:
        score = priority_score(business_impact=0.6, seo_impact=0.7, confidence=0.75,
                               feasibility=0.4, risk=0.4)
        out.append(Detected(
            type="consolidate_cannibalization",
            normalized_key=_key("cannibalization", str(grp["keyword"])),
            title=f"{grp['count']} pages competing for '{grp['keyword']}'",
            url=None, url_pattern=f"keyword:{grp['keyword']}", action_class="HIGH_RISK_WRITE",
            priority=bucket(score), score=score,
            inputs={"business_impact": 0.6, "seo_impact": 0.7, "confidence": 0.75,
                    "feasibility": 0.4, "risk": 0.4},
            detector="content_detector",
            recommendation=f"Consolidate the competing pages for '{grp['keyword']}' into one "
                           "canonical target; 301 the rest.",
            verification_method="confirm one indexable canonical target; others redirect",
            expected_outcome="single page ranks for the keyword; combined authority",
        ))
    for url, flags in flags_by_url.items():
        if "thin" in flags:
            score = priority_score(business_impact=0.5, seo_impact=0.6, confidence=0.8,
                                   feasibility=0.4, risk=0.3)
            out.append(Detected(
                type="improve_thin_content",
                normalized_key=_key("thin", url), title=f"Thin content: {url}",
                url=url, url_pattern=None, action_class="HIGH_RISK_WRITE",
                priority=bucket(score), score=score,
                inputs={"business_impact": 0.5, "seo_impact": 0.6, "confidence": 0.8,
                        "feasibility": 0.4, "risk": 0.3},
                detector="content_detector",
                recommendation="Expand the page to cover the SERP's common subtopics, or "
                               "consolidate it if the topic is served elsewhere.",
                verification_method="word count + subtopic coverage re-check",
                expected_outcome="page depth matches ranking peers",
            ))
    return out
