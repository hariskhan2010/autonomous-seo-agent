"""SEO-detection golden test (A-TO-Z-PLAN.md §Phase 3 eval).

A small fixture site with a hand-labelled issue ledger → precision/recall per the engine.
`analyze` is pure, so this is fully offline."""

from __future__ import annotations

from seo_core.technical import analyze
from seo_core.technical.models import PageView, SiteContext
from tests.eval.runner import prf

ORIGIN = "https://shop.test"


def _page(path: str, **kw: object) -> PageView:
    url = ORIGIN + path
    defaults = dict(
        url=url, final_url=url, http_status=200, title="Gemstone Rings — Buying Guide",
        meta_description="A guide to buying gemstone rings.", canonical=url, h1="Guide",
        headings={"h1": ["Guide"]}, word_count=400,
        schema_blocks=[{"@type": "Article"}],
    )
    defaults.update(kw)
    return PageView(**defaults)  # type: ignore[arg-type]


# ── fixture site + hand-labelled expected check codes ──────────────────────────
PAGES = [
    _page("/"),  # clean
    _page("/no-title", title=None),                                    # title_missing
    _page("/bad-canon", canonical="https://shop.test/other"),          # canonical_not_self
    _page("/noindex", robots_meta="noindex, follow"),                  # noindex_on_indexable
    _page("/thin", word_count=40),                                     # thin_content
    _page("/no-h1", h1=None, headings={}),                             # h1_missing
    _page("/UPPER/Path"),                                             # url_uppercase
    _page("/facets?color=red&size=9"),                                 # url_query_params + faceted_nav
    _page("/no-schema", schema_blocks=[]),                             # schema_missing
    _page("/missing-alt", images=[{"src": "/a.jpg", "alt": ""}]),      # img_missing_alt
    _page("/404", http_status=404),                                    # status_4xx
    _page("/orphan"),                                                  # orphan_page (nothing links to it)
    _page("/dup-a", title="Exact Same Title Here"),                    # title_duplicate
    _page("/dup-b", title="Exact Same Title Here"),                    # title_duplicate
]
# link graph: home links to most pages, but not /orphan
PAGES[0].internal_links = [p.final_url for p in PAGES[1:] if p.path != "/orphan"]

EXPECTED = {
    ("title_missing", "/no-title"),
    ("canonical_not_self", "/bad-canon"),
    ("noindex_on_indexable", "/noindex"),
    ("thin_content", "/thin"),
    ("h1_missing", "/no-h1"),
    ("url_uppercase", "/UPPER/Path"),
    ("url_query_params", "/facets"),
    ("faceted_nav", "/facets"),
    ("schema_missing", "/no-schema"),
    ("img_missing_alt", "/missing-alt"),
    ("status_4xx", "/404"),
    ("orphan_page", "/orphan"),
    ("broken_internal_link", "/"),   # home links to /404
    ("title_duplicate", None),
}


def _key(f) -> tuple[str, str | None]:  # noqa: ANN001
    if f.check_code == "title_duplicate":
        return ("title_duplicate", None)
    path = (f.url or "").replace(ORIGIN, "").split("?")[0] or None
    return (f.check_code, path)


def test_precision_recall_against_ledger() -> None:
    site = SiteContext(origin=ORIGIN, sitemap_urls=[], robots_has_sitemap=False)
    found = {_key(f) for f in analyze(PAGES, site)}

    tp = len(found & EXPECTED)
    fp = len(found - EXPECTED - {("robots_no_sitemap", None)})  # site-level, not in the page ledger
    fn = len(EXPECTED - found)
    scores = prf(tp, fp, fn)
    assert scores["recall"] >= 0.85, (scores, EXPECTED - found)
    assert scores["precision"] >= 0.9, (scores, found - EXPECTED)


def test_findings_are_severity_sorted() -> None:
    site = SiteContext(origin=ORIGIN, sitemap_urls=[])
    out = analyze(PAGES, site)
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    sev_seq = [rank[f.severity] for f in out]
    assert sev_seq == sorted(sev_seq)


def test_idempotent_keys_are_stable() -> None:
    site = SiteContext(origin=ORIGIN, sitemap_urls=[])
    a = {f.normalized_key for f in analyze(PAGES, site)}
    b = {f.normalized_key for f in analyze(PAGES, site)}
    assert a == b
