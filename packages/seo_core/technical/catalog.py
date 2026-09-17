"""Check catalogue (A-TO-Z-PLAN.md §Phase 3 — ported check set from
seo-agent/skills/technical-seo-checker + on-page-auditor).

code -> (category, severity, title template, fix). The engine emits findings against these."""

from __future__ import annotations

from typing import NamedTuple

DETECTOR_VERSION = "0.1.0"


class Check(NamedTuple):
    category: str
    severity: str
    title: str
    fix: str


CATALOG: dict[str, Check] = {
    # ── indexability ──
    "status_4xx": Check("indexability", "high", "Page returns a 4xx error", "Fix the broken URL or return a proper 410/redirect."),
    "status_5xx": Check("indexability", "critical", "Page returns a 5xx error", "Investigate the server error; 5xx pages are dropped from the index."),
    "noindex_on_indexable": Check("indexability", "high", "Indexable page has noindex", "Remove the noindex directive if this page should rank."),
    "canonical_missing": Check("indexability", "medium", "Missing canonical tag", "Add a self-referencing canonical link."),
    "canonical_not_self": Check("indexability", "high", "Canonical points to a different URL", "Point the canonical at this page's own URL unless consolidation is intended."),
    "canonical_to_non200": Check("indexability", "high", "Canonical targets a non-200 URL", "Point the canonical at a live, indexable URL."),
    "redirect_chain": Check("indexability", "medium", "Redirect chain (2+ hops)", "Collapse to a single 301 to the final URL."),
    "soft_404": Check("indexability", "medium", "Possible soft 404 (200 with empty/'not found' body)", "Return a real 404/410 status for missing content."),
    # ── on_page ──
    "title_missing": Check("on_page", "high", "Missing <title>", "Add a unique, descriptive title tag."),
    "title_long": Check("on_page", "low", "Title over 60 characters", "Trim to ~50–60 characters so it isn't truncated in SERPs."),
    "title_short": Check("on_page", "low", "Title under 15 characters", "Expand to a descriptive 30–60 characters."),
    "title_duplicate": Check("on_page", "medium", "Duplicate <title> across pages", "Give each page a unique title."),
    "meta_desc_missing": Check("on_page", "low", "Missing meta description", "Add a 120–160 character meta description."),
    "h1_missing": Check("on_page", "medium", "Missing <h1>", "Add a single descriptive H1."),
    "h1_multiple": Check("on_page", "low", "Multiple <h1> elements", "Use exactly one H1 per page."),
    "thin_content": Check("on_page", "medium", "Thin content (<150 words)", "Expand the page or consolidate it."),
    # ── urls ──
    "url_query_params": Check("urls", "low", "URL contains query parameters", "Prefer clean paths; ensure parameterised URLs are canonicalised."),
    "url_uppercase": Check("urls", "low", "URL contains uppercase letters", "Use lowercase URLs to avoid duplicate-content variants."),
    "url_too_long": Check("urls", "low", "URL over 115 characters", "Shorten the URL/slug."),
    "faceted_nav": Check("urls", "medium", "Faceted-navigation URL pattern detected", "Block or canonicalise filter/sort parameter combinations."),
    # ── links ──
    "img_missing_alt": Check("links", "low", "Image missing alt text", "Add descriptive alt text (or empty alt for decorative images)."),
    "broken_internal_link": Check("links", "high", "Internal link to a non-200 URL", "Fix or remove the broken internal link."),
    "orphan_page": Check("links", "medium", "Orphan page (no internal links point to it)", "Add contextual internal links from related pages."),
    # ── schema ──
    "schema_missing": Check("schema", "low", "No structured data (JSON-LD)", "Add relevant schema.org markup (Organization/Product/Article/FAQ)."),
    "schema_no_type": Check("schema", "low", "JSON-LD block without @type", "Add a valid @type to each JSON-LD block."),
    # ── hreflang ──
    "hreflang_no_self": Check("hreflang", "medium", "hreflang set has no self-reference", "Include a self-referencing hreflang entry on every localised page."),
    "hreflang_to_non200": Check("hreflang", "high", "hreflang targets a non-200 URL", "Point every hreflang at a live URL."),
    # ── crawlability (site-level) ──
    "robots_no_sitemap": Check("crawlability", "low", "robots.txt has no Sitemap reference", "Add a 'Sitemap:' line to robots.txt."),
    "robots_unreachable": Check("crawlability", "high", "robots.txt is not reachable", "Serve robots.txt at the site root with a 200 status."),
    "sitemap_empty": Check("crawlability", "high", "Sitemap contains no URLs", "Regenerate the sitemap with valid <loc> entries."),
    "in_sitemap_not_crawlable": Check("crawlability", "medium", "Sitemap URL is not reachable (non-200)", "Remove dead URLs from the sitemap."),
    "crawled_not_in_sitemap": Check("crawlability", "low", "Indexable page missing from the sitemap", "Add the page to the sitemap."),
    # ── duplicates ──
    "near_duplicate": Check("duplicates", "medium", "Near-duplicate content across URLs", "Consolidate with canonical/redirect, or differentiate the content."),
    # ── performance (Core Web Vitals — Phase 3 deferred item) ──
    "cwv_lcp_poor": Check("performance", "high", "Largest Contentful Paint is poor (>4.0s)", "Compress/preload the LCP image, cut render-blocking CSS/JS, and consider a CDN."),
    "cwv_inp_poor": Check("performance", "high", "Interaction to Next Paint is poor (>500ms)", "Break up long JavaScript tasks and defer non-critical scripts to cut main-thread work."),
    "cwv_cls_poor": Check("performance", "medium", "Cumulative Layout Shift is poor (>0.25)", "Reserve size for images/embeds/ads; avoid injecting content above existing content."),
    "cwv_ttfb_poor": Check("performance", "medium", "Time to First Byte is poor (>1.8s)", "Improve backend response time, add caching/CDN, and avoid slow redirect chains."),
}
