"""Technical SEO engine (A-TO-Z-PLAN.md §Phase 3, §V — 100% deterministic, no LLM).

`analyze(pages, site)` runs every check over a crawl's `PageView`s + `SiteContext` and returns
a de-duplicated list of `Finding`s. The worker turns each into a `seo_issues` row that cites the
snapshot proving it."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator

from seo_core.technical.catalog import CATALOG
from seo_core.technical.models import Finding, PageView, SiteContext

_FACET_PARAM = re.compile(r"[?&](color|size|sort|filter|price|brand|page|orderby)=", re.I)
_NOT_FOUND_TEXT = re.compile(r"\b(page not found|404|doesn'?t exist|no longer available)\b", re.I)


def _f(code: str, **kw: object) -> Finding:
    c = CATALOG[code]
    return Finding(check_code=code, category=c.category, severity=c.severity, title=c.title, fix=c.fix, **kw)  # type: ignore[arg-type]


def _page_checks(p: PageView) -> Iterator[Finding]:
    st = p.http_status
    if st and 400 <= st < 500:
        yield _f("status_4xx", url=p.final_url, detail={"status": st})
        return
    if st and st >= 500:
        yield _f("status_5xx", url=p.final_url, detail={"status": st})
        return

    if len(p.redirect_chain) >= 2:
        yield _f("redirect_chain", url=p.url, detail={"hops": len(p.redirect_chain), "chain": p.redirect_chain})

    if p.is_indexable_status:
        if p.is_noindex:
            yield _f("noindex_on_indexable", url=p.final_url, detail={"robots_meta": p.robots_meta})
        if not p.canonical:
            yield _f("canonical_missing", url=p.final_url)
        elif p.canonical.rstrip("/") != p.final_url.rstrip("/"):
            yield _f("canonical_not_self", url=p.final_url, detail={"canonical": p.canonical})

        # on-page
        if not p.title:
            yield _f("title_missing", url=p.final_url)
        elif len(p.title) > 60:
            yield _f("title_long", url=p.final_url, detail={"length": len(p.title)})
        elif len(p.title) < 15:
            yield _f("title_short", url=p.final_url, detail={"length": len(p.title)})

        if not p.meta_description:
            yield _f("meta_desc_missing", url=p.final_url)

        h1s = p.headings.get("h1", [])
        if not h1s:
            yield _f("h1_missing", url=p.final_url)
        elif len(h1s) > 1:
            yield _f("h1_multiple", url=p.final_url, detail={"count": len(h1s)})

        if 0 < p.word_count < 150:
            yield _f("thin_content", url=p.final_url, detail={"word_count": p.word_count})
            if p.word_count < 30 and _NOT_FOUND_TEXT.search(p.body_text or p.title or ""):
                yield _f("soft_404", url=p.final_url)
        elif p.word_count == 0 and _NOT_FOUND_TEXT.search(p.title or ""):
            yield _f("soft_404", url=p.final_url)

        # urls
        if "?" in p.final_url:
            yield _f("url_query_params", url=p.final_url)
            if _FACET_PARAM.search(p.final_url):
                yield _f("faceted_nav", url=p.final_url, url_pattern=p.final_url.split("?")[0] + "?*")
        if any(c.isupper() for c in p.path):
            yield _f("url_uppercase", url=p.final_url)
        if len(p.final_url) > 115:
            yield _f("url_too_long", url=p.final_url, detail={"length": len(p.final_url)})

        # images
        no_alt = [i["src"] for i in p.images if not i.get("alt")]
        if no_alt:
            yield _f("img_missing_alt", url=p.final_url, detail={"count": len(no_alt), "examples": no_alt[:5]})

        # schema
        if not p.schema_blocks:
            yield _f("schema_missing", url=p.final_url)
        elif any("@type" not in b for b in p.schema_blocks):
            yield _f("schema_no_type", url=p.final_url)

        # hreflang
        if p.hreflang:
            selfref = any(h.get("href", "").rstrip("/") == p.final_url.rstrip("/") for h in p.hreflang)
            if not selfref:
                yield _f("hreflang_no_self", url=p.final_url, detail={"entries": len(p.hreflang)})


def _site_checks(pages: list[PageView], site: SiteContext) -> Iterator[Finding]:
    by_norm = {site.norm(p.final_url): p for p in pages}
    status_ok = {n for n, p in by_norm.items() if p.http_status == 200}

    if not site.robots_reachable:
        yield _f("robots_unreachable", url_pattern=f"{site.origin}/robots.txt")
    elif not site.robots_has_sitemap:
        yield _f("robots_no_sitemap", url_pattern=f"{site.origin}/robots.txt")

    if site.sitemap_urls is not None and len(site.sitemap_urls) == 0 and site.robots_has_sitemap:
        yield _f("sitemap_empty", url_pattern=f"{site.origin}/sitemap.xml")

    sitemap_norm = {site.norm(u) for u in site.sitemap_urls}
    for u in site.sitemap_urls:
        n = site.norm(u)
        if n in by_norm and by_norm[n].http_status not in (200, None):
            yield _f("in_sitemap_not_crawlable", url=u, detail={"status": by_norm[n].http_status})
    for n in status_ok:
        if sitemap_norm and n not in sitemap_norm and not by_norm[n].is_noindex:
            yield _f("crawled_not_in_sitemap", url=by_norm[n].final_url)

    # canonical / hreflang targets → non-200 (only meaningful for live pages)
    for p in pages:
        if p.http_status != 200:
            continue
        if p.canonical and p.canonical.rstrip("/") != p.final_url.rstrip("/"):
            cn = site.norm(p.canonical)
            if cn in by_norm and by_norm[cn].http_status not in (200, None):
                yield _f("canonical_to_non200", url=p.final_url, detail={"canonical": p.canonical})
        for h in p.hreflang:
            tgt = site.norm(h.get("href", ""))
            if tgt in by_norm and by_norm[tgt].http_status not in (200, None):
                yield _f("hreflang_to_non200", url=p.final_url, detail={"target": h.get("href")})

    # internal link graph → broken links + orphans
    incoming: Counter[str] = Counter()
    for p in pages:
        for link in p.internal_links:
            n = site.norm(link)
            incoming[n] += 1
            if n in by_norm and by_norm[n].http_status not in (200, None):
                yield _f("broken_internal_link", url=p.final_url, detail={"target": link, "status": by_norm[n].http_status})
    for n in status_ok:
        pv = by_norm[n]
        if incoming[n] == 0 and pv.path not in ("", "/"):
            yield _f("orphan_page", url=pv.final_url)

    # duplicate titles
    titles = Counter(p.title for p in pages if p.title and p.http_status == 200)
    for title, count in titles.items():
        if count > 1:
            urls = [p.final_url for p in pages if p.title == title][:10]
            yield _f("title_duplicate", url_pattern=f"title:{title[:60]}", detail={"count": count, "urls": urls})

    # near-duplicate content (identical simhash across URLs)
    fps: dict[str, list[str]] = {}
    for p in pages:
        if p.content_fingerprint and p.http_status == 200:
            fps.setdefault(p.content_fingerprint, []).append(p.final_url)
    for fp, urls in fps.items():
        if len(urls) > 1:
            yield _f("near_duplicate", url_pattern=f"fingerprint:{fp}", detail={"urls": urls[:10]})


def analyze(pages: list[PageView], site: SiteContext) -> list[Finding]:
    seen: set[str] = set()
    out: list[Finding] = []
    for finding in (*(_pc for p in pages for _pc in _page_checks(p)), *_site_checks(pages, site)):
        if finding.normalized_key in seen:
            continue
        seen.add(finding.normalized_key)
        out.append(finding)
    sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    out.sort(key=lambda f: (sev_rank.get(f.severity, 9), f.check_code))
    return out
