"""Content signals: thin / outdated / cannibalization / consolidation
(A-TO-Z-PLAN.md §Phase 5, §V — deterministic)."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass

UTC = dt.UTC


@dataclass
class ContentRow:
    url: str
    content_type: str
    word_count: int
    primary_keyword: str | None = None
    updated_at: dt.datetime | None = None
    internal_links_in: int = 0


def content_flags(row: ContentRow, *, now: dt.datetime | None = None, stale_after_days: int = 540) -> list[str]:
    now = now or dt.datetime.now(UTC)
    flags: list[str] = []
    thin_floor = {"article": 300, "product": 80, "category": 50}.get(row.content_type, 150)
    if 0 < row.word_count < thin_floor:
        flags.append("thin")
    if row.updated_at and (now - row.updated_at).days > stale_after_days and row.content_type == "article":
        flags.append("outdated")
    if row.internal_links_in == 0 and row.content_type in ("article", "product"):
        flags.append("orphan")
    return flags


def cannibalization_groups(rows: list[ContentRow]) -> list[dict[str, object]]:
    """Pages competing for the same primary keyword → consolidation candidates."""
    by_kw: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        if r.primary_keyword:
            by_kw[r.primary_keyword.lower().strip()].append(r.url)
    return [
        {"keyword": kw, "urls": urls, "count": len(urls)}
        for kw, urls in by_kw.items()
        if len(urls) > 1
    ]
