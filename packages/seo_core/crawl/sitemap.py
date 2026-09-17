"""Tier 4 — sitemap & robots parsing (A-TO-Z-PLAN.md §Phase 2). Deterministic.

Fallback inventory when crawling is blocked, plus the robots rules Tier 1 must honour."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from bs4 import BeautifulSoup

_SITEMAP_IN_ROBOTS = re.compile(r"(?im)^\s*sitemap:\s*(\S+)")


@dataclass
class RobotsRules:
    allow: list[str] = field(default_factory=list)
    disallow: list[str] = field(default_factory=list)
    crawl_delay: float | None = None
    sitemaps: list[str] = field(default_factory=list)

    def can_fetch(self, path: str) -> bool:
        # Longest-match wins (standard robots precedence).
        best_len, decision = -1, True
        for rule, allowed in (
            *[(p, True) for p in self.allow],
            *[(p, False) for p in self.disallow],
        ):
            if rule and path.startswith(rule) and len(rule) > best_len:
                best_len, decision = len(rule), allowed
        return decision


def parse_robots(text: str, *, user_agent: str = "*") -> RobotsRules:
    """Per robots.txt precedence: use the most specific group whose `User-agent` matches, and
    ONLY that group — never merge rules across groups (a `*` group must not leak into a
    `GPTBot`-specific query just because both appear in the file)."""
    rules = RobotsRules()
    rules.sitemaps = _SITEMAP_IN_ROBOTS.findall(text)

    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    directives: list[tuple[str, str]] = []
    seen_directive = False

    def _flush() -> None:
        nonlocal agents, directives, seen_directive
        if agents:
            groups.append((agents, directives))
        agents, directives, seen_directive = [], [], False

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field_name, _, value = line.partition(":")
        field_name, value = field_name.strip().lower(), value.strip()
        if field_name == "user-agent":
            if seen_directive:
                _flush()
            agents.append(value)
        elif field_name in ("disallow", "allow", "crawl-delay") and agents:
            directives.append((field_name, value))
            seen_directive = True
    _flush()

    ua = user_agent.lower()
    chosen: list[tuple[str, str]] | None = None
    wildcard: list[tuple[str, str]] | None = None
    for group_agents, group_directives in groups:
        lowers = [a.lower() for a in group_agents]
        if wildcard is None and "*" in lowers:
            wildcard = group_directives
        if ua in lowers:
            chosen = group_directives
            break
    for field_name, value in chosen if chosen is not None else (wildcard or []):
        if field_name == "disallow" and value:
            rules.disallow.append(value)
        elif field_name == "allow" and value:
            rules.allow.append(value)
        elif field_name == "crawl-delay":
            try:
                rules.crawl_delay = float(value)
            except ValueError:
                pass
    return rules


def parse_sitemap(xml: str, *, base_url: str = "") -> tuple[list[str], list[str]]:
    """Returns (page_urls, nested_sitemap_urls)."""
    soup = BeautifulSoup(xml, "lxml-xml")
    if soup.find("sitemapindex"):
        nested = [urljoin(base_url, loc.get_text(strip=True)) for loc in soup.select("sitemap > loc")]
        return [], nested
    pages = [urljoin(base_url, loc.get_text(strip=True)) for loc in soup.select("url > loc")]
    return pages, []
