"""Knowledge-graph read/write over Postgres (A-TO-Z-PLAN.md §G).

Idempotent upserts (natural key per node type; edges on (src,dst,relation)). Traversal = a
recursive CTE with a depth cap + visited-set. Lexical retrieval = tsvector + pg_trgm; the vector
half is added when the EMBEDDING role is live."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from db.models.graph import KgEdge, KgNode


@dataclass
class NodeRef:
    id: uuid.UUID
    type: str
    label: str


class KnowledgeGraph:
    def __init__(self, session: Session, tenant_id: uuid.UUID, project_id: uuid.UUID) -> None:
        self.s = session
        self.tid = tenant_id
        self.pid = project_id

    # ── write ───────────────────────────────────────────────
    def upsert_node(self, *, type: str, ref_id: str, label: str, props: dict[str, object] | None = None) -> uuid.UUID:
        stmt = insert(KgNode).values(
            tenant_id=self.tid, project_id=self.pid, type=type, ref_id=ref_id,
            label=label, props=props or {},
            search_tsv=func.to_tsvector("english", f"{label} {type}"),
        ).on_conflict_do_update(
            constraint="uq_kg_nodes_project_type_ref",
            set_={"label": label, "props": props or {},
                  "search_tsv": func.to_tsvector("english", f"{label} {type}")},
        ).returning(KgNode.id)
        return self.s.execute(stmt).scalar_one()

    def upsert_edge(self, src: uuid.UUID, dst: uuid.UUID, relation: str, *,
                    weight: float = 1.0, props: dict[str, object] | None = None) -> uuid.UUID:
        stmt = insert(KgEdge).values(
            tenant_id=self.tid, project_id=self.pid, src=src, dst=dst, relation=relation,
            weight=weight, props=props or {},
        ).on_conflict_do_update(
            constraint="uq_kg_edges_src_dst_rel",
            set_={"weight": weight, "props": props or {}},
        ).returning(KgEdge.id)
        return self.s.execute(stmt).scalar_one()

    # ── read ────────────────────────────────────────────────
    def node(self, type: str, ref_id: str) -> KgNode | None:
        return self.s.execute(
            select(KgNode).where(
                KgNode.project_id == self.pid, KgNode.type == type, KgNode.ref_id == ref_id
            )
        ).scalar_one_or_none()

    def neighbours(self, node_id: uuid.UUID, *, relation: str | None = None,
                   direction: str = "out") -> list[NodeRef]:
        col_from, col_to = (KgEdge.src, KgEdge.dst) if direction == "out" else (KgEdge.dst, KgEdge.src)
        q = select(KgNode).join(KgEdge, KgNode.id == col_to).where(col_from == node_id)
        if relation:
            q = q.where(KgEdge.relation == relation)
        return [NodeRef(n.id, n.type, n.label) for n in self.s.execute(q).scalars()]

    def traverse(self, start: uuid.UUID, *, relation: str | None = None,
                 max_depth: int = 4) -> list[tuple[uuid.UUID, int]]:
        """BFS via recursive CTE. Returns [(node_id, depth)] excluding the start."""
        rel_filter = "AND e.relation = :rel" if relation else ""
        sql = text(f"""
            WITH RECURSIVE walk(id, depth, path) AS (
                SELECT CAST(:start AS uuid), 0, ARRAY[CAST(:start AS uuid)]
              UNION ALL
                SELECT e.dst, w.depth + 1, w.path || e.dst
                FROM walk w
                JOIN kg_edges e ON e.src = w.id {rel_filter}
                WHERE w.depth < :max_depth AND NOT e.dst = ANY(w.path)
            )
            SELECT id, min(depth) AS depth FROM walk WHERE depth > 0 GROUP BY id
        """)
        params: dict[str, object] = {"start": str(start), "max_depth": max_depth}
        if relation:
            params["rel"] = relation
        return [(r.id, r.depth) for r in self.s.execute(sql, params)]

    def search(self, query: str, *, node_type: str | None = None, limit: int = 20) -> list[NodeRef]:
        """Hybrid-lite: full-text rank + trigram similarity, fused. Vector half added with §Z."""
        type_filter = "AND type = :ntype" if node_type else ""
        sql = text(f"""
            SELECT id, type, label,
                   ts_rank(search_tsv, plainto_tsquery('english', :q)) AS ts_score,
                   similarity(label, :q) AS trgm_score
            FROM kg_nodes
            WHERE project_id = :pid {type_filter}
              AND (search_tsv @@ plainto_tsquery('english', :q) OR similarity(label, :q) > 0.1)
            ORDER BY (ts_rank(search_tsv, plainto_tsquery('english', :q)) + similarity(label, :q)) DESC
            LIMIT :limit
        """)
        params: dict[str, object] = {"q": query, "pid": str(self.pid), "limit": limit}
        if node_type:
            params["ntype"] = node_type
        return [NodeRef(r.id, r.type, r.label) for r in self.s.execute(sql, params)]

    def orphan_pages(self) -> list[NodeRef]:
        sql = text("""
            SELECT n.id, n.type, n.label FROM kg_nodes n
            WHERE n.project_id = :pid AND n.type = 'Page'
              AND NOT EXISTS (SELECT 1 FROM kg_edges e WHERE e.dst = n.id AND e.relation = 'links_to')
        """)
        return [NodeRef(r.id, r.type, r.label) for r in self.s.execute(sql, {"pid": str(self.pid)})]
