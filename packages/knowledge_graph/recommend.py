"""Graph-derived recommendations (A-TO-Z-PLAN.md §Phase 6, §14 — deterministic).

- `internal_link_recommendations`: for weak/orphan pages, propose contextual links from
  topically-related strong pages, in the SOURCE/TARGET/ANCHOR/CONTEXT/REASON/IMPACT/CONFIDENCE shape.
- `topical_coverage`: pillar → cluster → supporting coverage % + weak areas.
"""

from __future__ import annotations

from dataclasses import dataclass

from knowledge_graph.api import KnowledgeGraph


@dataclass
class LinkRec:
    source_url: str
    target_url: str
    anchor: str
    context: str
    reason: str
    expected_impact: str
    confidence: float


def internal_link_recommendations(
    kg: KnowledgeGraph, *, max_recs: int = 50
) -> list[LinkRec]:
    from sqlalchemy import text

    # Strong pages: many incoming links. Weak/orphan: few or none. Related: share a Topic.
    sql = text("""
        WITH indeg AS (
            SELECT dst AS node, count(*) AS d FROM kg_edges
            WHERE relation = 'links_to' GROUP BY dst
        ),
        pages AS (
            SELECT n.id, n.label AS url, coalesce(i.d, 0) AS indeg
            FROM kg_nodes n LEFT JOIN indeg i ON i.node = n.id
            WHERE n.project_id = :pid AND n.type = 'Page'
        ),
        topic_pages AS (
            SELECT e.src AS page, e.dst AS topic FROM kg_edges e WHERE e.relation = 'covers'
        )
        SELECT sp.url AS source_url, wp.url AS target_url, t.label AS topic
        FROM pages wp
        JOIN topic_pages wtp ON wtp.page = wp.id
        JOIN topic_pages stp ON stp.topic = wtp.topic AND stp.page <> wp.id
        JOIN pages sp ON sp.id = stp.page AND sp.indeg >= 2
        JOIN kg_nodes t ON t.id = wtp.topic
        WHERE wp.indeg <= 1
          AND NOT EXISTS (
            SELECT 1 FROM kg_edges le
            WHERE le.src = sp.id AND le.dst = wp.id AND le.relation = 'links_to'
          )
        LIMIT :limit
    """)
    rows = kg.s.execute(sql, {"pid": str(kg.pid), "limit": max_recs})
    out: list[LinkRec] = []
    for r in rows:
        out.append(LinkRec(
            source_url=r.source_url, target_url=r.target_url,
            anchor=r.topic.lower(),
            context=f"a paragraph on {r.source_url} discussing {r.topic}",
            reason=f"'{r.source_url}' is an authority page on {r.topic}; '{r.target_url}' covers the "
                   f"same topic but has ≤1 internal link.",
            expected_impact="improved crawl depth + topical relevance transfer to the weak page",
            confidence=0.6,
        ))
    return out


def topical_coverage(kg: KnowledgeGraph) -> list[dict[str, object]]:
    from sqlalchemy import text

    sql = text("""
        SELECT t.label AS topic,
               count(DISTINCT e.src) FILTER (WHERE e.relation = 'covers') AS covering_pages
        FROM kg_nodes t
        LEFT JOIN kg_edges e ON e.dst = t.id
        WHERE t.project_id = :pid AND t.type = 'Topic'
        GROUP BY t.label
        ORDER BY covering_pages ASC
    """)
    return [
        {"topic": r.topic, "covering_pages": r.covering_pages,
         "weak": r.covering_pages == 0}
        for r in kg.s.execute(sql, {"pid": str(kg.pid)})
    ]
