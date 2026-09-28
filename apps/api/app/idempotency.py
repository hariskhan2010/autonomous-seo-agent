"""`Idempotency-Key` for mutating endpoints (docs/API.md: "Mutations accept `Idempotency-Key`
header -> stored in `job_runs`; replay returns prior result").

Reuses the existing idempotency-key ledger — `db.models.runtime.JobRun` (`job_runs`, migration
0001, unique `idempotency_key`) — rather than adding a table. Semantics (Stripe-style):
- No header -> the endpoint behaves exactly as before.
- First request with a key -> a `job_runs` row is written in the SAME transaction as the
  endpoint's own writes, holding the response. If the endpoint fails (any exception), the whole
  transaction rolls back, the row with it, and the key is free to retry — errors are not cached.
- Same key + same request -> the stored response is replayed (same status code, header
  `Idempotent-Replayed: true`) and the endpoint body does not run again.
- Same key + different request -> 422. Same key while the first is still in flight -> 409.

The ledger key is `api:` + sha256(tenant | scope | client key), so two tenants (or two endpoints)
using the same client key can never collide on the globally-unique column, and a raw client key
is never stored."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Header, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models.runtime import JobRun

IdempotencyKeyHeader = Annotated[
    str | None,
    Header(alias="Idempotency-Key", min_length=1, max_length=255,
           description="Optional. Retrying with the same key replays the first response."),
]
REPLAYED_HEADER = "Idempotent-Replayed"


def ledger_key(tenant_id: uuid.UUID, scope: str, key: str) -> str:
    digest = hashlib.sha256(f"{tenant_id}|{scope}|{key}".encode()).hexdigest()
    return f"api:{digest}"


def request_hash(request: object) -> str:
    canonical = json.dumps(request, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass
class Idempotency:
    """Handle returned by `begin`. If `replayed`, return `body` straight away; otherwise do the
    work and call `store(status_code, body)` before returning."""

    db: Session | None = None
    row: JobRun | None = None
    replayed: bool = False
    body: Any = None

    def store(self, status_code: int, body: Any) -> None:
        if self.row is None or self.db is None:  # no header sent — nothing to record
            return
        result = dict(self.row.result or {})
        result.update({"status_code": status_code, "body": body})
        self.row.result = result
        self.row.status = "succeeded"
        self.row.finished_at = dt.datetime.now(dt.UTC)
        self.db.add(self.row)


def _lookup(db: Session, key: str) -> JobRun | None:
    return db.execute(select(JobRun).where(JobRun.idempotency_key == key)).scalar_one_or_none()


def _replay(row: JobRun, req_hash: str, response: Response) -> Idempotency:
    result = row.result or {}
    if result.get("request_hash") != req_hash:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Idempotency-Key was already used with a different request",
        )
    if row.status != "succeeded":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "a request with this Idempotency-Key is still in progress"
        )
    response.status_code = int(result.get("status_code", status.HTTP_200_OK))
    response.headers[REPLAYED_HEADER] = "true"
    return Idempotency(replayed=True, body=result.get("body"))


def begin(
    db: Session, response: Response, *, tenant_id: uuid.UUID, scope: str, key: str | None,
    request: object,
) -> Idempotency:
    """Claim `key` for this request, or replay the response it already produced.
    `request` is anything JSON-able that identifies the request (path params + body)."""
    if key is None:
        return Idempotency()
    lk, rh = ledger_key(tenant_id, scope, key), request_hash(request)
    existing = _lookup(db, lk)
    if existing is not None:
        return _replay(existing, rh, response)

    row = JobRun(tenant_id=tenant_id, idempotency_key=lk, job_type=f"api.{scope}",
                 status="running", attempts=1, result={"request_hash": rh})
    try:
        with db.begin_nested():  # SAVEPOINT — a lost race must not poison the outer transaction
            db.add(row)
            db.flush()
    except IntegrityError:
        # A concurrent request with the same key inserted first. If it has committed by now we
        # can replay it; if it's still in flight, tell the client to retry later.
        winner = _lookup(db, lk)
        if winner is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "a request with this Idempotency-Key is still in progress",
            ) from None
        return _replay(winner, rh, response)
    return Idempotency(db=db, row=row)
