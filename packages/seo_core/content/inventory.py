"""Content classification (A-TO-Z-PLAN.md §Phase 5 — deterministic).

Assigns a `content_type` to a crawled page from URL shape + schema + DOM signals."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_PRODUCT_RE = re.compile(r"/(product|products|p|item|shop)/", re.I)
_CATEGORY_RE = re.compile(r"/(category|categories|collection|collections|c|shop|catalog)(/|$)", re.I)
_ARTICLE_RE = re.compile(r"/(blog|article|articles|news|guide|guides|post|posts|resources)/", re.I)


def classify_content_type(
    *, url: str, schema_types: list[str] | None = None, word_count: int = 0,
    has_price: bool = False, internal_link_count: int = 0,
) -> str:
    path = urlsplit(url).path or "/"
    types = {t.lower() for t in (schema_types or [])}

    if path in ("", "/"):
        return "home"
    if {"product", "offer"} & types or _PRODUCT_RE.search(path) or has_price:
        return "product"
    if {"collectionpage", "itemlist"} & types or _CATEGORY_RE.search(path):
        return "category"
    if {"article", "blogposting", "newsarticle"} & types or _ARTICLE_RE.search(path):
        return "article"
    if {"faqpage", "howto"} & types:
        return "article"
    if word_count >= 300 and internal_link_count < 15:
        return "article"
    if internal_link_count >= 20 and word_count < 300:
        return "category"
    return "landing" if word_count < 300 else "other"
