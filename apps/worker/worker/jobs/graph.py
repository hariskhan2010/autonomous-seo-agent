"""`graph.build` worker job (A-TO-Z-PLAN.md §Phase 6).

Idempotent, re-runnable. Builds nodes + edges from crawl results, keywords, SERP runs, and
content items. Edges cite the evidence that supports them where one exists."""

from __future__ import annotations

import uuid

import structlog

from db.models.content import ContentItem, Topic
from db.models.crawl import CrawlResult
from db.models.events import OutboxEvent
from db.models.keywords import Keyword, KeywordCluster
from db.models.serp import SerpResult, SerpRun
from db.session import tenant_session
from knowledge_graph.api import KnowledgeGraph
from seo_core.crawl.fingerprint import content_hash

log = structlog.get_logger("job.graph")


def run(tenant_id: str, project_id: str, crawl_run_id: str | None = None,
        correlation_id: str | None = None) -> dict[str, object]:
    tid, pid = uuid.UUID(tenant_id), uuid.UUID(project_id)
    nodes = edges = 0

    with tenant_session(tid, pid) as s:
        kg = KnowledgeGraph(s, tid, pid)

        # Pages + internal links
        results = s.query(CrawlResult).filter(
            CrawlResult.project_id == pid, CrawlResult.http_status == 200
        ).all()
        page_node: dict[str, uuid.UUID] = {}
        for r in results:
            nid = kg.upsert_node(type="Page", ref_id=content_hash(r.url), label=r.url,
                                 props={"title": r.title, "word_count": r.word_count})
            page_node[r.url] = nid
            nodes += 1
        for r in results:
            for link in r.internal_links or []:
                dst = page_node.get(link)
                if dst and dst != page_node[r.url]:
                    kg.upsert_edge(page_node[r.url], dst, "links_to")
                    edges += 1

        # Keywords + clusters (Topic) + ranks_for
        for kw in s.query(Keyword).filter(Keyword.project_id == pid).all():
            knid = kg.upsert_node(type="Keyword", ref_id=str(kw.id), label=kw.term,
                                  props={"volume": kw.volume})
            nodes += 1
            if kw.cluster_id:
                cl = s.get(KeywordCluster, kw.cluster_id)
                if cl:
                    tnid = kg.upsert_node(type="Topic", ref_id=cl.slug, label=cl.name)
                    kg.upsert_edge(knid, tnid, "appears_in")
                    edges += 1

        # SERP → ranks_for (our pages + competitor domains)
        for run_row in s.query(SerpRun).filter(SerpRun.project_id == pid).all():
            qnid = kg.upsert_node(type="Query", ref_id=content_hash(run_row.query), label=run_row.query)
            nodes += 1
            for res in s.query(SerpResult).filter(SerpResult.serp_run_id == run_row.id).all():
                dom_label = res.domain
                cnid = kg.upsert_node(
                    type="Competitor" if res.is_competitor else "Page",
                    ref_id=content_hash(res.url), label=res.url or dom_label,
                )
                kg.upsert_edge(cnid, qnid, "ranks_for", props={"position": res.position})
                edges += 1

        # Content items → covers Topic
        for ci in s.query(ContentItem).filter(ContentItem.project_id == pid).all():
            if ci.topic_id:
                tp = s.get(Topic, ci.topic_id)
                if tp:
                    pnid = page_node.get(ci.url) or kg.upsert_node(
                        type="Page", ref_id=content_hash(ci.url), label=ci.url
                    )
                    tnid = kg.upsert_node(type="Topic", ref_id=tp.slug, label=tp.name)
                    kg.upsert_edge(pnid, tnid, "covers")
                    edges += 1

        s.add(OutboxEvent(
            tenant_id=tid, project_id=pid, type="graph.built", version=1,
            correlation_id=correlation_id or str(uuid.uuid4()),
            payload={"nodes": nodes, "edges": edges},
        ))

    log.info("graph.built", nodes=nodes, edges=edges)
    return {"nodes": nodes, "edges": edges}
