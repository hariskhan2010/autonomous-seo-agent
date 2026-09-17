"""Knowledge graph build + query against Neon (A-TO-Z-PLAN.md §Phase 6 acceptance)."""

from __future__ import annotations

import uuid

import pytest

from db.models.events import OutboxEvent
from db.models.graph import KgEdge, KgNode
from db.models.identity import Tenant
from db.models.project import Project
from db.session import tenant_session
from knowledge_graph import KnowledgeGraph, internal_link_recommendations


@pytest.fixture
def project():
    t, p = uuid.uuid4(), uuid.uuid4()
    with tenant_session(t, p) as s:
        s.add(Tenant(id=t, name="T", slug=f"t-{t.hex[:8]}"))
        s.add(Project(id=p, tenant_id=t, name="P", slug="p", approval_mode="read_only"))
    yield t, p
    with tenant_session(t, p) as s:
        for m in (KgEdge, KgNode, OutboxEvent, Project, Tenant):
            s.query(m).delete()


def test_build_traverse_search_and_recommend(project) -> None:
    t, p = project
    with tenant_session(t, p) as s:
        kg = KnowledgeGraph(s, t, p)
        home = kg.upsert_node(type="Page", ref_id="home", label="https://x.com/")
        guide = kg.upsert_node(type="Page", ref_id="guide", label="https://x.com/guide")
        deep = kg.upsert_node(type="Page", ref_id="deep", label="https://x.com/deep")
        orphan = kg.upsert_node(type="Page", ref_id="orphan", label="https://x.com/orphan")
        topic = kg.upsert_node(type="Topic", ref_id="emeralds", label="Emeralds")

        kg.upsert_edge(home, guide, "links_to")
        kg.upsert_edge(guide, deep, "links_to")
        kg.upsert_edge(home, deep, "links_to")   # home has indeg 0, guide indeg 1, deep indeg 2
        kg.upsert_edge(deep, topic, "covers")
        kg.upsert_edge(orphan, topic, "covers")  # orphan covers same topic, indeg 0

        # idempotency
        kg.upsert_edge(home, guide, "links_to")
        assert s.query(KgEdge).filter(KgEdge.relation == "links_to").count() == 3

        reachable = {nid for nid, _ in kg.traverse(home, relation="links_to")}
        assert {guide, deep} <= reachable

        orphans = {n.label for n in kg.orphan_pages()}
        assert "https://x.com/orphan" in orphans and "https://x.com/home" not in orphans

        hits = kg.search("emeralds", node_type="Topic")
        assert any(h.label == "Emeralds" for h in hits)

        recs = internal_link_recommendations(kg)
        # deep (indeg 2, strong) → orphan (indeg 0, same topic) is a recommendation
        assert any(r.target_url == "https://x.com/orphan" and r.source_url == "https://x.com/deep"
                   for r in recs)
