# 0002 — PostgreSQL knowledge graph first (no Neo4j)

- Status: accepted
- Date: 2026-09-06

## Context
The system needs a typed knowledge graph (pages, keywords, topics, entities, competitors,
issues, opportunities, changes…) with traversal and semantic neighbour queries
(A-TO-Z-PLAN.md §G).

## Decision
Model the graph as `kg_nodes` + `kg_edges` in PostgreSQL:
- Traversal via recursive CTEs with a depth cap + visited-set; common traversals materialised
  as SQL functions/views.
- Lexical retrieval via `tsvector` (GIN) + `pg_trgm`.
- Semantic retrieval via `pgvector` against the dedicated `embeddings` table.
- Hybrid ranking = reciprocal-rank fusion of lexical + vector, optional graph re-rank.
- Every edge is evidence-backed via `evidence_links` (many evidence rows per edge).

## Consequences
- One datastore, one backup story, transactional writes across domain + graph.
- Deep/wide traversal performance must be watched; mitigations are partial indexes + materialised
  traversals before considering a graph DB.

## Alternatives considered
- Neo4j now: rejected — adds a datastore, a query language, a sync problem, and ops burden before
  any measured need. Revisit only with an ADR carrying profiled query traces that CTEs can't serve.
