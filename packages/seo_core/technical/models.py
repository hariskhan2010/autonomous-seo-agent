"""Data views for the technical engine (A-TO-Z-PLAN.md §Phase 3).

`PageView` is a plain projection of a `crawl_results` row + its snapshot — the engine is pure and
never touches the DB, so it's trivially testable with fixtures."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit


@dataclass
class PageView:
    url: str
    final_url: str
    http_status: int | None
    title: str | None = None
    meta_description: str | None = None
    canonical: str | None = None
    robots_meta: str | None = None
    h1: str | None = None
    headings: dict[str, list[str]] = field(default_factory=dict)
    word_count: int = 0
    internal_links: list[str] = field(default_factory=list)
    external_links: list[str] = field(default_factory=list)
    images: list[dict[str, str]] = field(default_factory=list)
    schema_blocks: list[dict[str, object]] = field(default_factory=list)
    hreflang: list[dict[str, str]] = field(default_factory=list)
    redirect_chain: list[dict[str, str]] = field(default_factory=list)
    content_fingerprint: str | None = None
    body_text: str = ""

    @property
    def path(self) -> str:
        return urlsplit(self.final_url).path or "/"

    @property
    def is_indexable_status(self) -> bool:
        return self.http_status == 200

    @property
    def is_noindex(self) -> bool:
        return bool(self.robots_meta and "noindex" in self.robots_meta)

    @classmethod
    def from_parsed(cls, parsed: Any) -> PageView:
        """Adapt a `seo_core.crawl.parser.ParsedPage` (or any object with the same fields)."""
        return cls(
            url=str(getattr(parsed, "url", "")),
            final_url=str(getattr(parsed, "final_url", "")),
            http_status=getattr(parsed, "http_status", None),
            title=getattr(parsed, "title", None),
            meta_description=getattr(parsed, "meta_description", None),
            canonical=getattr(parsed, "canonical", None),
            robots_meta=getattr(parsed, "robots_meta", None),
            h1=getattr(parsed, "h1", None),
            headings=getattr(parsed, "headings", {}) or {},
            word_count=int(getattr(parsed, "word_count", 0) or 0),
            internal_links=list(getattr(parsed, "internal_links", []) or []),
            external_links=list(getattr(parsed, "external_links", []) or []),
            images=list(getattr(parsed, "images", []) or []),
            schema_blocks=list(getattr(parsed, "schema_blocks", []) or []),
            hreflang=list(getattr(parsed, "hreflang", []) or []),
            redirect_chain=list(getattr(parsed, "redirect_chain", []) or []),
            content_fingerprint=getattr(parsed, "content_fingerprint", None),
            body_text=str(getattr(parsed, "text_for_fingerprint", "")
                          or getattr(parsed, "body_text", "") or ""),
        )


@dataclass
class SiteContext:
    origin: str
    sitemap_urls: list[str] = field(default_factory=list)
    robots_has_sitemap: bool = True
    robots_reachable: bool = True
    # filled by the engine
    _incoming: dict[str, int] = field(default_factory=dict)

    def norm(self, url: str) -> str:
        p = urlsplit(url)
        return f"{p.scheme}://{p.netloc.lower()}{(p.path.rstrip('/') or '/')}"


@dataclass
class Finding:
    check_code: str
    category: str
    severity: str
    title: str
    fix: str
    url: str | None = None
    url_pattern: str | None = None
    detail: dict[str, object] = field(default_factory=dict)

    @property
    def normalized_key(self) -> str:
        basis = f"{self.check_code}|{self.url_pattern or self.url or '*'}"
        return hashlib.sha256(basis.encode()).hexdigest()
