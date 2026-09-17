# 0007 — Transactional outbox for events

- Status: accepted
- Date: 2026-09-06

## Context
The system is event-driven (`crawl.completed`, `seo.issue.detected`, `opportunity.created`,
`verification.failed`…). A "publish to Redis after commit" approach loses events on crash between
commit and publish, and double-delivers on retry (A-TO-Z-PLAN.md §F.3, §AA).

## Decision
- Any state change that must emit an event writes the domain row **and** an `outbox_events` row
  in the **same transaction**.
- A relay poller publishes unpublished rows to the bus (at-least-once) and marks them sent.
- `outbox_events(event_id uuid unique, type, version, correlation_id, causation_id, payload,
  created_at, published_at, attempts)`.
- Consumers are idempotent: `processed_events(event_id, consumer)` + no-op on replay.
- Backoff on relay + consumers; after N attempts → dead-letter table + ops view + manual replay.
- The DB is the source of truth for events; the bus is transport.

## Consequences
- Slight write amplification and a relay process to run.
- All consumers must be written idempotently — enforced in review + an eval fixture.

## Alternatives considered
- CDC/Debezium: rejected for now — heavier infra than a polling relay needs at this scale.
- Direct bus publish: rejected — the reliability hole above.
