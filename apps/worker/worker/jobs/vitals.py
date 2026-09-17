"""`vitals.analyze` worker job (A-TO-Z-PLAN.md §Phase 3 — Core Web Vitals).

Pulls PageSpeed Insights (lab + field, when available) for a URL, records the raw metrics as an
`evidence` row (kind='pagespeed'), evaluates them against Google's CWV thresholds, and upserts any
poor-rated metric into `seo_issues` — the same idempotent, evidence-linked path `technical.run`
uses, so CWV findings land in the same issue list rather than a separate one."""

from __future__ import annotations

import datetime as dt
import uuid

import structlog
from integrations.pagespeed import get_vitals_provider

from db.models.events import OutboxEvent
from db.models.evidence import Evidence, EvidenceLink
from db.models.issues import SeoIssue
from db.session import tenant_session
from seo_core.confidence import score as confidence_score
from seo_core.crawl.fingerprint import content_hash
from seo_core.technical.catalog import DETECTOR_VERSION
from seo_core.technical.vitals import evaluate_vitals

log = structlog.get_logger("job.vitals")
UTC = dt.UTC


def analyze(tenant_id: str, project_id: str, url: str, *, strategy: str = "mobile",
           provider_name: str = "pagespeed", use_fake: bool = False,
           correlation_id: str | None = None) -> dict[str, object]:
    tid, pid = uuid.UUID(tenant_id), uuid.UUID(project_id)
    provider = get_vitals_provider("fake" if use_fake else provider_name)
    metrics_list = provider.fetch(url, strategy=strategy)
    now = dt.datetime.now(UTC)

    created, updated = 0, 0
    by_sev: dict[str, int] = {}
    with tenant_session(tid, pid) as s:
        for metrics in metrics_list:
            ch = content_hash(
                f"{url}|{strategy}|{metrics.source}|{metrics.lcp_ms}|{metrics.inp_ms}|"
                f"{metrics.cls}|{metrics.ttfb_ms}"
            )
            # Content-addressed, like page_snapshots: an unchanged reading isn't a new evidence row.
            ev = s.query(Evidence).filter(
                Evidence.tenant_id == tid, Evidence.content_hash == ch, Evidence.kind == "pagespeed",
            ).one_or_none()
            if ev is None:
                ev = Evidence(
                    tenant_id=tid, project_id=pid, kind="pagespeed", source_url=url,
                    content_hash=ch, provider=provider.name, parser="seo_core.technical.vitals",
                    parser_version=DETECTOR_VERSION, collected_at=now,
                    confidence=confidence_score("pagespeed"),
                    props={"strategy": metrics.strategy, "source": metrics.source,
                           "lcp_ms": metrics.lcp_ms, "inp_ms": metrics.inp_ms,
                           "cls": metrics.cls, "ttfb_ms": metrics.ttfb_ms},
                )
                s.add(ev)
                s.flush()

            for fnd in evaluate_vitals(metrics):
                by_sev[fnd.severity] = by_sev.get(fnd.severity, 0) + 1
                existing = s.query(SeoIssue).filter(
                    SeoIssue.project_id == pid, SeoIssue.normalized_key == fnd.normalized_key,
                ).one_or_none()
                if existing is None:
                    issue = SeoIssue(
                        tenant_id=tid, project_id=pid, crawl_run_id=None, check_code=fnd.check_code,
                        category=fnd.category, severity=fnd.severity, title=fnd.title,
                        url=fnd.url, url_pattern=fnd.url_pattern, detail=fnd.detail, fix=fnd.fix,
                        normalized_key=fnd.normalized_key, status="open",
                        detector_version=DETECTOR_VERSION, first_seen=now, last_seen=now,
                        seen_count=1,
                    )
                    s.add(issue)
                    s.flush()
                    created += 1
                else:
                    existing.last_seen = now
                    existing.seen_count += 1
                    existing.detail = fnd.detail
                    existing.severity = fnd.severity
                    if existing.status == "resolved":
                        existing.status = "regressed"
                    s.add(existing)
                    s.flush()
                    issue = existing
                    updated += 1

                link_exists = s.query(EvidenceLink).filter(
                    EvidenceLink.evidence_id == ev.id, EvidenceLink.subject_type == "issue",
                    EvidenceLink.subject_id == issue.id,
                ).first()
                if link_exists is None:
                    s.add(EvidenceLink(
                        tenant_id=tid, project_id=pid, evidence_id=ev.id,
                        subject_type="issue", subject_id=issue.id,
                    ))

        s.add(OutboxEvent(
            tenant_id=tid, project_id=pid, type="vitals.analyzed", version=1,
            correlation_id=correlation_id or str(uuid.uuid4()),
            payload={"url": url, "strategy": strategy, "created": created, "updated": updated,
                     "by_severity": by_sev},
        ))

    log.info("vitals.analyzed", url=url, created=created, updated=updated, by_severity=by_sev)
    return {"created": created, "updated": updated, "by_severity": by_sev}
