"""GEO machine-readability + entity-consistency track (A-TO-Z-PLAN.md §Phase 10 — deterministic,
§V). Answers: can the AI crawlers that feed chat/AI-Overview answers even read this site, and
does the site declare a consistent, machine-readable brand entity? No LLM, no network — consumes
crawl evidence already collected (robots.txt text, parsed JSON-LD, an optional llms.txt body)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from seo_core.crawl.sitemap import parse_robots

# Known AI-answer / AI-training crawlers most GEO guidance recommends explicitly allowing.
AI_CRAWLERS = (
    "GPTBot", "ChatGPT-User", "OAI-SearchBot",       # OpenAI
    "ClaudeBot", "Claude-Web", "anthropic-ai",        # Anthropic
    "Google-Extended",                                # Gemini / AI Overviews training
    "PerplexityBot",                                  # Perplexity
    "CCBot",                                          # Common Crawl (feeds many LLMs)
    "Amazonbot", "Applebot-Extended",
)

_ORG_TYPES = {"organization", "brand", "localbusiness", "corporation", "onlinebusiness"}


@dataclass
class MachineReadabilityReport:
    ai_crawler_access: dict[str, bool] = field(default_factory=dict)
    blocked_crawlers: list[str] = field(default_factory=list)
    organization_schema_present: bool = False
    organization_name_match: bool | None = None  # None = no org schema to check
    same_as_present: bool = False
    llms_txt_present: bool = False
    llms_txt_well_formed: bool | None = None  # None = not present
    issues: list[str] = field(default_factory=list)


def check_ai_crawler_access(robots_text: str | None) -> dict[str, bool]:
    """True = allowed to fetch `/` (robots.txt absent or empty ⇒ allowed, same as real crawlers)."""
    if not robots_text:
        return {ua: True for ua in AI_CRAWLERS}
    return {ua: parse_robots(robots_text, user_agent=ua).can_fetch("/") for ua in AI_CRAWLERS}


def _flatten_schema(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for b in blocks:
        graph = b.get("@graph")
        if isinstance(graph, list):
            out.extend(n for n in graph if isinstance(n, dict))
        else:
            out.append(b)
    return out


def check_organization_schema(
    schema_blocks: list[dict[str, Any]], *, brand: str
) -> tuple[bool, bool | None, bool]:
    """Returns (present, name_match, same_as_present)."""
    for node in _flatten_schema(schema_blocks):
        types = node.get("@type")
        types = [types] if isinstance(types, str) else (types or [])
        if not any(str(t).lower() in _ORG_TYPES for t in types):
            continue
        name = str(node.get("name") or "").strip().lower()
        match = brand.strip().lower() in name or name in brand.strip().lower() if name else False
        same_as = node.get("sameAs")
        has_same_as = bool(same_as) and (
            isinstance(same_as, list) and len(same_as) > 0 or isinstance(same_as, str)
        )
        return True, match, has_same_as
    return False, None, False


def check_llms_txt(text: str | None) -> tuple[bool, bool | None]:
    """`llms.txt` convention: an H1 title line + at least one markdown link section.
    Returns (present, well_formed)."""
    if text is None:
        return False, None
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    has_title = bool(lines) and lines[0].startswith("# ")
    has_link = any(ln.startswith("- [") or ln.startswith("[") for ln in lines)
    return True, has_title and has_link


def audit_machine_readability(
    *,
    brand: str,
    robots_text: str | None = None,
    schema_blocks: list[dict[str, Any]] | None = None,
    llms_txt_text: str | None = None,
) -> MachineReadabilityReport:
    access = check_ai_crawler_access(robots_text)
    blocked = sorted(ua for ua, ok in access.items() if not ok)
    org_present, name_match, same_as = check_organization_schema(schema_blocks or [], brand=brand)
    llms_present, llms_well_formed = check_llms_txt(llms_txt_text)

    issues: list[str] = [f"ai_crawler_blocked:{ua}" for ua in blocked]
    if not org_present:
        issues.append("no_organization_schema")
    elif name_match is False:
        issues.append("organization_name_mismatch")
    if org_present and not same_as:
        issues.append("no_same_as_links")
    if not llms_present:
        issues.append("no_llms_txt")
    elif llms_well_formed is False:
        issues.append("llms_txt_malformed")

    return MachineReadabilityReport(
        ai_crawler_access=access,
        blocked_crawlers=blocked,
        organization_schema_present=org_present,
        organization_name_match=name_match,
        same_as_present=same_as,
        llms_txt_present=llms_present,
        llms_txt_well_formed=llms_well_formed,
        issues=issues,
    )
