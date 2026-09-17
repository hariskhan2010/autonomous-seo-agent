"""`technical.analyze` worker job (A-TO-Z-PLAN.md §Phase 3).

Consumes a crawl's `crawl_results` + `page_snapshots`, runs the deterministic technical engine,
and upserts `seo_issues` (idempotent on `normalized_key`). Each issue is linked to the snapshot
`evidence` row that proves it. Emits `seo.issue.detected` counts via the outbox."""

from __future__ import annotations

import datetime as dt
import uuid

import structlog

from db.models.crawl import CrawlResult, CrawlRun, PageSnapshot
from db.models.events import OutboxEvent
from db.models.evidence import Evidence, EvidenceLink
from db.models.issues import SeoIssue
from db.models.project import Website
from db.session import tenant_session
from seo_core.technical import analyze
from seo_core.technical.catalog import DETECTOR_VERSION
from seo_core.technical.models import PageView, SiteContext

log = structlog.get_logger("job.technical")
UTC = dt.UTC


def _page_view(res: CrawlResult, snap: PageSnapshot | None) -> PageView:
    return PageView(
        url=res.url, final_url=(snap.final_url if snap else res.url), http_status=res.http_status,
        title=res.title, meta_description=res.meta_description, canonical=res.canonical,
        robots_meta=res.robots_meta, h1=res.h1, headings=res.headings or {},
        word_count=res.word_count, internal_links=list(res.internal_links or []),
        external_links=list(res.external_links or []), images=list(res.images or []),
        schema_blocks=list(res.schema_blocks or []), hreflang=list(res.hreflang or []),
        redirect_chain=(snap.redirect_chain if snap else []),
        content_fingerprint=(snap.content_fingerprint if snap else None),
    )


def run(tenant_id: str, project_id: str, crawl_run_id: str,
        correlation_id: str | None = None) -> dict[str, object]:
    tid, pid, rid = uuid.UUID(tenant_id), uuid.UUID(project_id), uuid.UUID(crawl_run_id)
    corr = correlation_id or str(uuid.uuid4())
    now = dt.datetime.now(UTC)

    with tenant_session(tid, pid) as s:
        crawl_run = s.get(CrawlRun, rid)
        if crawl_run is None:
            raise ValueError("crawl_run not found")
        website = s.get(Website, crawl_run.website_id)
        results = s.query(CrawlResult).filter(CrawlResult.crawl_run_id == rid).all()
        snaps = {
            sn.id: sn for sn in s.query(PageSnapshot).filter(PageSnapshot.crawl_run_id == rid).all()
        }
        # evidence rows for this run, keyed by content_hash → snapshot → link target
        ev_by_snapshot = {
            e.snapshot_id: e.id
            for e in s.query(Evidence).filter(Evidence.crawl_run_id == rid).all()
        }
        pages = [_page_view(r, snaps.get(r.snapshot_id)) for r in results]
        stats = crawl_run.stats or {}
        site = SiteContext(
            origin=(website.origin if website else ""),
            sitemap_urls=list(stats.get("sitemap_urls", [])),
            robots_reachable=bool(stats.get("robots_reachable", True)),
            robots_has_sitemap=bool(stats.get("robots_has_sitemap", True)),
        )
        # map final_url -> evidence_id (via result -> snapshot -> evidence)
        ev_for_url = {
            r.url: ev_by_snapshot.get(r.snapshot_id) for r in results
        }

        findings = analyze(pages, site)

        created, updated = 0, 0
        by_sev: dict[str, int] = {}
        for fnd in findings:
            by_sev[fnd.severity] = by_sev.get(fnd.severity, 0) + 1
            existing = (
                s.query(SeoIssue)
                .filter(SeoIssue.project_id == pid, SeoIssue.normalized_key == fnd.normalized_key)
                .one_or_none()
            )
            if existing is None:
                issue = SeoIssue(
                    tenant_id=tid, project_id=pid, crawl_run_id=rid, check_code=fnd.check_code,
                    category=fnd.category, severity=fnd.severity, title=fnd.title, url=fnd.url,
                    url_pattern=fnd.url_pattern, detail=fnd.detail, fix=fnd.fix,
                    normalized_key=fnd.normalized_key, status="open",
                    detector_version=DETECTOR_VERSION, first_seen=now, last_seen=now, seen_count=1,
                )
                s.add(issue)
                s.flush()
                created += 1
            else:
                existing.last_seen = now
                existing.seen_count += 1
                existing.crawl_run_id = rid
                existing.detail = fnd.detail
                existing.severity = fnd.severity
                if existing.status == "resolved":
                    existing.status = "regressed"
                s.add(existing)
                s.flush()
                issue = existing

            ev_id = ev_for_url.get(fnd.url) if fnd.url else None
            if ev_id is not None:
                link_exists = (
                    s.query(EvidenceLink)
                    .filter(
                        EvidenceLink.evidence_id == ev_id,
                        EvidenceLink.subject_type == "issue",
                        EvidenceLink.subject_id == issue.id,
                    )
                    .first()
                )
                if link_exists is None:
                    s.add(EvidenceLink(
                        tenant_id=tid, project_id=pid, evidence_id=ev_id,
                        subject_type="issue", subject_id=issue.id,
                    ))

        s.add(OutboxEvent(
            tenant_id=tid, project_id=pid, type="seo.issue.detected", version=1,
            correlation_id=corr,
            payload={"crawl_run_id": crawl_run_id, "created": created, "updated": updated, "by_severity": by_sev},
        ))

    log.info("technical.analyzed", crawl_run_id=crawl_run_id, findings=len(findings),
             created=created, updated=updated, by_severity=by_sev)
    return {"findings": len(findings), "created": created, "updated": updated, "by_severity": by_sev}
