"""Deterministic HTML parsing (A-TO-Z-PLAN.md §Phase 2, §V — no LLM).

Turns a raw HTML body + response metadata into the structured `CrawlResult` shape the
technical/content engines consume. Every value here is derivable from the bytes."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

_WS = re.compile(r"\s+")


def _text(node: object) -> str:
    if node is None:
        return ""
    return _WS.sub(" ", node.get_text(" ", strip=True)).strip()


@dataclass
class ParsedPage:
    url: str
    final_url: str
    http_status: int | None
    title: str | None = None
    meta_description: str | None = None
    canonical: str | None = None
    robots_meta: str | None = None
    h1: str | None = None
    word_count: int = 0
    headings: dict[str, list[str]] = field(default_factory=dict)
    internal_links: list[str] = field(default_factory=list)
    external_links: list[str] = field(default_factory=list)
    images: list[dict[str, str]] = field(default_factory=list)
    schema_blocks: list[dict[str, object]] = field(default_factory=list)
    hreflang: list[dict[str, str]] = field(default_factory=list)
    text_for_fingerprint: str = ""


def _same_site(a: str, b: str) -> bool:
    ha, hb = urlsplit(a).netloc.lower(), urlsplit(b).netloc.lower()
    return ha == hb or ha.removeprefix("www.") == hb.removeprefix("www.")


def parse_html(body: str, *, url: str, final_url: str, http_status: int | None) -> ParsedPage:
    soup = BeautifulSoup(body, "lxml")
    page = ParsedPage(url=url, final_url=final_url, http_status=http_status)

    if soup.title:
        page.title = _text(soup.title) or None

    for m in soup.find_all("meta"):
        name = (m.get("name") or "").lower()
        if name == "description":
            page.meta_description = (m.get("content") or "").strip() or None
        elif name == "robots":
            page.robots_meta = (m.get("content") or "").strip().lower() or None

    link_canon = soup.find("link", rel=lambda v: v and "canonical" in v)
    if link_canon and link_canon.get("href"):
        page.canonical = urljoin(final_url, link_canon["href"].strip())

    for alt in soup.find_all("link", rel=lambda v: v and "alternate" in v):
        if alt.get("hreflang"):
            page.hreflang.append(
                {"hreflang": alt["hreflang"].strip(), "href": urljoin(final_url, alt.get("href", ""))}
            )

    for level in ("h1", "h2", "h3"):
        vals = [_text(h) for h in soup.find_all(level) if _text(h)]
        if vals:
            page.headings[level] = vals
    page.h1 = page.headings.get("h1", [None])[0]

    seen_int: set[str] = set()
    seen_ext: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            continue
        absu = urljoin(final_url, href)
        if urlsplit(absu).scheme not in ("http", "https"):
            continue
        if _same_site(absu, final_url):
            norm = absu.split("#")[0]
            if norm not in seen_int:
                seen_int.add(norm)
                page.internal_links.append(norm)
        elif absu not in seen_ext:
            seen_ext.add(absu)
            page.external_links.append(absu)

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if src:
            page.images.append(
                {"src": urljoin(final_url, src.strip()), "alt": (img.get("alt") or "").strip()}
            )

    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or tag.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        page.schema_blocks.extend(data if isinstance(data, list) else [data])

    body_text = _text(soup.body) if soup.body else _text(soup)
    page.word_count = len(body_text.split())
    page.text_for_fingerprint = body_text
    return page
