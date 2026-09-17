"""`opportunities.detect` worker job (A-TO-Z-PLAN.md §Phase 7).

Reads open `seo_issues` + content flags → detectors → upserts `opportunities` (idempotent on
`normalized_key`). Every opportunity is linked to the evidence of the issue that triggered it
(evidence_links subject_type='opportunity'); one with zero links is rejected. Emits
`opportunity.created` counts via the outbox."""

from __future__ import annotations

import datetime as dt
import uuid

import structlog

from db.models.content import ContentItem
from db.models.events import OutboxEvent
from db.models.evidence import EvidenceLink
from db.models.issues import SeoIssue
from db.models.opportunity import Opportunity
from db.session import tenant_session
from opportunity_engine import detect_from_content, detect_from_issues
from seo_core.content.signals import ContentRow, cannibalization_groups

log = structlog.get_logger("job.opportunities")
UTC = dt.UTC


def run(tenant_id: str, project_id: str, correlation_id: str | None = None) -> dict[str, object]:
    tid, pid = uuid.UUID(tenant_id), uuid.UUID(project_id)
    now = dt.datetime.now(UTC)

    with tenant_session(tid, pid) as s:
        issues = [
            {"id": str(i.id), "check_code": i.check_code, "severity": i.severity, "title": i.title,
             "url": i.url, "url_pattern": i.url_pattern, "fix": i.fix}
            for i in s.query(SeoIssue).filter(
                SeoIssue.project_id == pid, SeoIssue.status.in_(("open", "regressed"))
            ).all()
        ]
        # evidence for each issue
        ev_by_issue: dict[str, str] = {}
        for row in s.query(EvidenceLink).filter(
            EvidenceLink.project_id == pid, EvidenceLink.subject_type == "issue"
        ).all():
            ev_by_issue[str(row.subject_id)] = str(row.evidence_id)

        items = s.query(ContentItem).filter(ContentItem.project_id == pid).all()
        rows = [
            ContentRow(url=ci.url, content_type=ci.content_type, word_count=ci.word_count,
                       primary_keyword=(ci.props or {}).get("primary_keyword"))
            for ci in items
        ]
        flags_by_url = {ci.url: list(ci.flags or []) for ci in items}

        detected = [
            *detect_from_issues(issues),
            *detect_from_content(cannibalization_groups(rows), flags_by_url=flags_by_url),
        ]

        created = updated = rejected = 0
        by_priority: dict[str, int] = {}
        for d in detected:
            ev_ids = [ev_by_issue[i] for i in d.evidence_issue_ids if i in ev_by_issue]
            if d.detector == "issue_detector" and not ev_ids:
                rejected += 1
                continue  # no evidence → reject (§Phase 7 acceptance)
            by_priority[d.priority] = by_priority.get(d.priority, 0) + 1

            opp = s.query(Opportunity).filter(
                Opportunity.project_id == pid, Opportunity.normalized_key == d.normalized_key
            ).one_or_none()
            if opp is None:
                opp = Opportunity(
                    tenant_id=tid, project_id=pid, type=d.type, normalized_key=d.normalized_key,
                    url=d.url, url_pattern=d.url_pattern, title=d.title,
                    business_impact=d.inputs["business_impact"], seo_impact=d.inputs["seo_impact"],
                    confidence=d.inputs["confidence"], feasibility=d.inputs["feasibility"],
                    risk=d.inputs["risk"], score=d.score, priority=d.priority,
                    action_class=d.action_class, recommendation=d.recommendation,
                    verification_method=d.verification_method, expected_outcome=d.expected_outcome,
                    status="detected", detector=d.detector,
                    first_seen=now, last_seen=now, seen_count=1,
                )
                s.add(opp)
                s.flush()
                created += 1
            else:
                opp.last_seen = now
                opp.seen_count += 1
                opp.score = d.score
                opp.priority = d.priority
                if opp.status in ("completed", "failed"):
                    opp.status = "detected"
                s.add(opp)
                s.flush()
                updated += 1

            for ev_id in ev_ids:
                exists = s.query(EvidenceLink).filter(
                    EvidenceLink.evidence_id == uuid.UUID(ev_id),
                    EvidenceLink.subject_type == "opportunity",
                    EvidenceLink.subject_id == opp.id,
                ).first()
                if exists is None:
                    s.add(EvidenceLink(
                        tenant_id=tid, project_id=pid, evidence_id=uuid.UUID(ev_id),
                        subject_type="opportunity", subject_id=opp.id,
                    ))

        s.add(OutboxEvent(
            tenant_id=tid, project_id=pid, type="opportunity.created", version=1,
            correlation_id=correlation_id or str(uuid.uuid4()),
            payload={"created": created, "updated": updated, "rejected_no_evidence": rejected,
                     "by_priority": by_priority},
        ))

    log.info("opportunities.detected", created=created, updated=updated, rejected=rejected,
             by_priority=by_priority)
    return {"created": created, "updated": updated, "rejected_no_evidence": rejected,
            "by_priority": by_priority}
