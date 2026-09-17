"""Normalised SERP shape (A-TO-Z-PLAN.md §Phase 4).

Every provider adapter (SerpAPI, DataForSEO, …) maps its raw payload to `SerpPayload`, so the
analysis code never sees provider-specific JSON."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SerpItem:
    position: int
    url: str
    title: str = ""
    snippet: str = ""


@dataclass
class SerpFeatureRaw:
    type: str                       # one of db.models.serp.SERP_FEATURE_TYPES
    position: int | None = None
    items: list[str] = field(default_factory=list)   # e.g. PAA questions, video titles
    data: dict[str, object] = field(default_factory=dict)


@dataclass
class SerpPayload:
    query: str
    provider: str
    locale: str = "en-US"
    device: str = "desktop"
    organic: list[SerpItem] = field(default_factory=list)
    features: list[SerpFeatureRaw] = field(default_factory=list)
    related_searches: list[str] = field(default_factory=list)
    raw: dict[str, object] = field(default_factory=dict)


@dataclass
class SerpAnalysis:
    query: str
    top_domains: list[str]
    feature_types: list[str]
    questions: list[str]
    entities: list[tuple[str, float]]        # (term, weight)
    common_topics: list[str]
    own_position: int | None = None
    competitor_positions: dict[str, int] = field(default_factory=dict)
    content_gap: list[str] = field(default_factory=list)
