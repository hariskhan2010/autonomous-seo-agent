"""AI-response citation parsing (A-TO-Z-PLAN.md §Phase 10 — deterministic first pass, §V).

Extracts: is the brand mentioned (and roughly where), which competitors are mentioned, which URLs
are cited, is our own domain cited, coarse sentiment. A `FAST`-model pass refines the ambiguous
cases later; this is the reproducible floor scored against a labelled corpus."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

_URL_RE = re.compile(r"https?://[^\s)\]}>\"']+")
_NEG = re.compile(r"\b(avoid|scam|poor|worst|disappoint|overpriced|not recommended|beware)\b", re.I)
_POS = re.compile(r"\b(best|excellent|recommended|top choice|great|trusted|high quality|leading)\b", re.I)


@dataclass
class Citation:
    brand_mentioned: bool = False
    brand_position: int | None = None
    competitors_mentioned: list[str] = field(default_factory=list)
    cited_urls: list[str] = field(default_factory=list)
    own_url_cited: bool = False
    sentiment: str = "neutral"


def _domain(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.")


def parse_citations(
    text: str, *, brand: str, own_domain: str, competitor_names: list[str],
    competitor_domains: list[str] | None = None,
) -> Citation:
    low = text.lower()
    c = Citation()

    if brand and brand.lower() in low:
        c.brand_mentioned = True
        idx = low.index(brand.lower())
        # position = which "paragraph"/list item the first mention falls in
        c.brand_position = low[:idx].count("\n") + 1

    for name in competitor_names:
        if name and name.lower() in low and name.lower() != brand.lower():
            c.competitors_mentioned.append(name)

    urls = _URL_RE.findall(text)
    seen: set[str] = set()
    for u in urls:
        u = u.rstrip(".,);")
        if u not in seen:
            seen.add(u)
            c.cited_urls.append(u)
    own = own_domain.removeprefix("www.")
    comp_domains = {d.removeprefix("www.") for d in (competitor_domains or [])}
    c.own_url_cited = any(_domain(u) == own for u in c.cited_urls)
    for u in c.cited_urls:
        d = _domain(u)
        if d in comp_domains and d not in {x.lower() for x in c.competitors_mentioned}:
            c.competitors_mentioned.append(d)

    if c.brand_mentioned:
        window = low[max(0, low.index(brand.lower()) - 160): low.index(brand.lower()) + 160]
        if _NEG.search(window):
            c.sentiment = "negative"
        elif _POS.search(window):
            c.sentiment = "positive"

    return c
