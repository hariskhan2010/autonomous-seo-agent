"""`crawl.run` worker job (A-TO-Z-PLAN.md §Phase 2).

Ties the pure seo_core.crawl primitives to the DB + evidence store:
  fetch (Tier 1, SSRF-guarded, or Tier 2 headless-browser render — same guard, same `FetchResult`
  shape either way) → parse → fingerprint → object storage → page_snapshots + crawl_results +
  evidence rows → `crawl.completed` via the transactional outbox.

Idempotency-keyed. Tier 3 (proxy) is separate, not yet built. `CrawlOptions.tier="browser"`
selects Tier 2 (`seo_core.crawl.render`) — runs only in the Tier-2 container
(`infra/Dockerfile.playwright`); the default `tier="http"` never imports `playwright` at all."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
import structlog

from db.models.crawl import CrawlResult, CrawlRun, PageSnapshot
from db.models.events import OutboxEvent
from db.models.evidence import Evidence
from db.models.project import Website
from db.session import tenant_session
from seo_core.confidence import score as confidence_score
from seo_core.crawl.fetcher import FetchResult, HostRateLimiter, fetch
from seo_core.crawl.fingerprint import changed, content_hash, simhash
from seo_core.crawl.parser import parse_html
from seo_core.crawl.sitemap import parse_robots, parse_sitemap

log = structlog.get_logger("job.crawl")
UTC = dt.UTC


def _url_hash(url: str) -> str:
    p = urlsplit(url)
    path = (p.path.rstrip("/") or "/")
    return content_hash(f"{p.scheme}://{p.netloc.lower()}{path}?{p.query}")


@dataclass
class CrawlOptions:
    max_pages: int = 30
    max_depth: int = 2
    tier: str = "http"


@dataclass
class Discovery:
    seeds: list[str]
    delay: float
    sitemap_urls: list[str]
    robots_reachable: bool
    robots_has_sitemap: bool


async def _fetch_one(
    url: str, *, tier: str, client: httpx.AsyncClient, allowed: frozenset[str],
    limiter: HostRateLimiter,
) -> FetchResult:
    if tier == "browser":
        # Imported lazily — only the Tier-2 container (`infra/Dockerfile.playwright`) has the
        # `playwright` package's browser binary; the default `http` tier never touches this import.
        from seo_core.crawl.render import render

        return await render(url, allowed_hosts=allowed)
    return await fetch(url, client=client, allowed_hosts=allowed, limiter=limiter)


async def _discover(client: httpx.AsyncClient, origin: str, allowed: frozenset[str], limit: int) -> Discovery:
    """robots + sitemap → seed URL list, crawl delay, and site context for the technical engine."""
    delay = 1.0
    seeds: list[str] = [origin.rstrip("/") + "/"]
    sitemap_urls: list[str] = []
    rb = await fetch(origin.rstrip("/") + "/robots.txt", client=client, allowed_hosts=allowed)
    robots_reachable = rb.status == 200
    robots_has_sitemap = False
    if robots_reachable and rb.body:
        rules = parse_robots(rb.body.decode("utf-8", "ignore"))
        robots_has_sitemap = bool(rules.sitemaps)
        if rules.crawl_delay:
            delay = max(delay, rules.crawl_delay)
        for sm_url in rules.sitemaps[:2]:
            sm = await fetch(sm_url, client=client, allowed_hosts=allowed)
            if sm.status == 200 and sm.body:
                pages, _ = parse_sitemap(sm.body.decode("utf-8", "ignore"), base_url=sm_url)
                sitemap_urls.extend(pages)
                seeds.extend(pages)
    out, seen = [], set()
    for u in seeds:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return Discovery(out[:limit], delay, sitemap_urls, robots_reachable, robots_has_sitemap)


async def _run_async(tenant_id: uuid.UUID, project_id: uuid.UUID, website_id: uuid.UUID,
                     opts: CrawlOptions, correlation_id: str) -> dict[str, object]:
    with tenant_session(tenant_id, project_id) as s:
        website = s.get(Website, website_id)
        if website is None:
            raise ValueError("website not found for tenant/project")
        origin = website.origin
        allowed = frozenset({urlsplit(origin).hostname or ""})
        run = CrawlRun(
            tenant_id=tenant_id, project_id=project_id, website_id=website_id,
            state="running", tier_requested=opts.tier,
            options={"max_pages": opts.max_pages}, started_at=dt.datetime.now(UTC),
        )
        s.add(run)
        s.flush()
        run_id = run.id
        # prior fingerprints for delta detection
        prior = {
            r.url_hash: r.content_fingerprint
            for r in s.query(PageSnapshot).filter(PageSnapshot.project_id == project_id).all()
        }

    limiter = HostRateLimiter(default_delay=1.0)
    counts: dict[str, int] = {"fetched": 0, "blocked": 0, "errors": 0, "changed": 0, "unchanged": 0}
    site_ctx: dict[str, object] = {}

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
        disc = await _discover(client, origin, allowed, opts.max_pages)
        site_ctx = {
            "sitemap_urls": disc.sitemap_urls,
            "robots_reachable": disc.robots_reachable,
            "robots_has_sitemap": disc.robots_has_sitemap,
        }
        for h in allowed:
            limiter.set_delay(h, disc.delay)

        for url in disc.seeds:
            r = await _fetch_one(
                url, tier=opts.tier, client=client, allowed=allowed, limiter=limiter,
            )
            if r.blocked_reason:
                counts["blocked"] += 1
                log.warning("crawl.blocked", url=url, reason=r.blocked_reason)
                continue
            if not r.parseable or r.status >= 400 or not r.body:
                counts["errors"] += 1
                continue

            html = r.body.decode("utf-8", "ignore")
            ch = content_hash(r.body)
            fp = simhash(parse_html(html, url=url, final_url=r.final_url, http_status=r.status).text_for_fingerprint)
            uh = _url_hash(r.final_url)
            was_changed = changed(prior.get(uh), fp)
            counts["changed" if was_changed else "unchanged"] += 1
            counts["fetched"] += 1

            if not was_changed:
                continue  # no new snapshot for unchanged pages (§Phase 2 acceptance)

            parsed = parse_html(html, url=url, final_url=r.final_url, http_status=r.status)
            from common import storage
            key = storage.key_for(str(tenant_id), str(project_id), "raw_html", ch)
            raw_key: str | None = key
            try:
                storage.put_text(key, html)
            except Exception:  # noqa: BLE001 - storage optional in dev; snapshot still records the hash
                log.warning("crawl.storage_unavailable", key=key)
                raw_key = None

            with tenant_session(tenant_id, project_id) as s:
                snap = PageSnapshot(
                    tenant_id=tenant_id, project_id=project_id, crawl_run_id=run_id,
                    url=url, url_hash=uh, final_url=r.final_url, tier=opts.tier,
                    http_status=r.status, content_hash=ch, content_fingerprint=fp,
                    fetched_at=dt.datetime.now(UTC), raw_key=raw_key,
                    headers={k.lower(): v for k, v in r.headers.items()},
                    redirect_chain=r.redirect_chain,
                )
                s.add(snap)
                s.flush()
                ev = Evidence(
                    tenant_id=tenant_id, project_id=project_id, kind="http_response",
                    source_url=r.final_url, method="GET", http_status=r.status,
                    crawl_run_id=run_id, snapshot_id=snap.id, content_hash=ch,
                    provider="firsthand-crawl", parser="seo_core.crawl.parser", parser_version="0.1.0",
                    collected_at=dt.datetime.now(UTC), confidence=confidence_score("crawl"),
                )
                s.add(ev)
                s.flush()
                res = CrawlResult(
                    tenant_id=tenant_id, project_id=project_id, crawl_run_id=run_id,
                    snapshot_id=snap.id, url=url, url_hash=uh, http_status=r.status,
                    title=parsed.title, meta_description=parsed.meta_description,
                    canonical=parsed.canonical, robots_meta=parsed.robots_meta, h1=parsed.h1,
                    word_count=parsed.word_count, internal_links=parsed.internal_links,
                    external_links=parsed.external_links, images=parsed.images,
                    headings=parsed.headings, schema_blocks=parsed.schema_blocks,
                    hreflang=parsed.hreflang, changed_since_last=True,
                )
                s.add(res)
                # evidence rows stand alone here; Phase 3 links them to the issues they prove.

    stats: dict[str, object] = {**counts, **site_ctx}
    with tenant_session(tenant_id, project_id) as s:
        final_run = s.get(CrawlRun, run_id)
        if final_run is None:
            raise RuntimeError("crawl_run vanished mid-job")
        final_run.state = "completed"
        final_run.finished_at = dt.datetime.now(UTC)
        final_run.stats = stats
        s.add(final_run)
        s.add(OutboxEvent(
            tenant_id=tenant_id, project_id=project_id, type="crawl.completed", version=1,
            correlation_id=correlation_id,
            payload={"crawl_run_id": str(run_id), "website_id": str(website_id), "stats": counts},
        ))
    log.info("crawl.completed", crawl_run_id=str(run_id), **counts)
    return {"crawl_run_id": str(run_id), "stats": stats}


def run(tenant_id: str, project_id: str, website_id: str,
        options: dict[str, object] | None = None, correlation_id: str | None = None) -> dict[str, object]:
    opts = CrawlOptions(**(options or {}))  # type: ignore[arg-type]
    return asyncio.run(_run_async(
        uuid.UUID(tenant_id), uuid.UUID(project_id), uuid.UUID(website_id),
        opts, correlation_id or str(uuid.uuid4()),
    ))
