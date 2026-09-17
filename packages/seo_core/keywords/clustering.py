"""Keyword clustering (A-TO-Z-PLAN.md §Phase 4, §V — deterministic).

Ported from seo-agent/lib/clustering.py (token-Jaccard, volume-seeded greedy). Stable across
runs given the same input + threshold. Embedding-based clustering (pgvector) is layered on later
for the ambiguous tail — this is the reproducible baseline."""

from __future__ import annotations

from dataclasses import dataclass, field

from seo_core.keywords.intent import primary_intent
from seo_core.keywords.normalize import tokens


@dataclass
class KeywordInput:
    term: str
    volume: int | None = None


@dataclass
class Cluster:
    name: str
    slug: str
    terms: list[str] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    primary_intent: str = "informational"
    volume_sum: int = 0

    @property
    def size(self) -> int:
        return len(self.terms)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _slug(text: str) -> str:
    return "-".join(text.lower().split())[:120] or "cluster"


@dataclass
class _Node:
    i: int
    term: str
    vol: int
    tok: set[str]


def cluster_keywords(
    keywords: list[KeywordInput | str], *, threshold: float = 0.45
) -> list[Cluster]:
    items = [k if isinstance(k, KeywordInput) else KeywordInput(k) for k in keywords]
    nodes = [_Node(i, it.term, it.volume or 0, tokens(it.term)) for i, it in enumerate(items)]
    used: set[int] = set()
    clusters: list[Cluster] = []

    for seed in sorted(nodes, key=lambda n: (-n.vol, n.term)):
        if seed.i in used:
            continue
        group = [seed]
        used.add(seed.i)
        for other in nodes:
            if other.i in used:
                continue
            if _jaccard(seed.tok, other.tok) >= threshold:
                group.append(other)
                used.add(other.i)
        terms = [g.term for g in group]
        intents = sorted({primary_intent(t).value for t in terms})
        clusters.append(Cluster(
            name=seed.term, slug=_slug(seed.term), terms=terms, intents=intents,
            primary_intent=primary_intent(seed.term).value,
            volume_sum=sum(g.vol for g in group),
        ))
    clusters.sort(key=lambda c: (-c.volume_sum, -c.size, c.name))
    return clusters
