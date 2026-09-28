"""`Idempotency-Key` helper (Phase 12 deferral) over the existing `job_runs` ledger — no DB:
a tiny fake session stands in for SQLAlchemy. The real-Postgres path (incl. the unique-index
race and rollback-on-error) is covered by tests/integration/test_api_pagination_idempotency.py."""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from app import idempotency
from fastapi import HTTPException, Response

from db.models.runtime import JobRun

T1, T2 = uuid.uuid4(), uuid.uuid4()


class _FakeSession:
    """Just enough of `Session` for `idempotency.begin`: rows keyed by `idempotency_key`."""

    def __init__(self) -> None:
        self.rows: dict[str, JobRun] = {}
        self._pending: list[JobRun] = []

    @contextlib.contextmanager
    def begin_nested(self) -> Iterator[None]:
        yield

    def add(self, row: JobRun) -> None:
        self._pending.append(row)

    def flush(self) -> None:
        for row in self._pending:
            self.rows[row.idempotency_key] = row
        self._pending.clear()


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> _FakeSession:
    fake = _FakeSession()
    monkeypatch.setattr(idempotency, "_lookup", lambda _db, key: fake.rows.get(key))
    return fake


def _begin(db: Any, key: str | None, request: object, *, tenant: uuid.UUID = T1,
           scope: str = "plans.approve") -> tuple[idempotency.Idempotency, Response]:
    resp = Response()
    return idempotency.begin(db, resp, tenant_id=tenant, scope=scope, key=key,
                             request=request), resp


def test_ledger_key_is_namespaced_by_tenant_and_scope_and_hides_raw_key() -> None:
    k = idempotency.ledger_key(T1, "plans.approve", "client-key-123")
    assert k.startswith("api:")
    assert "client-key-123" not in k
    assert len(k) <= 120  # JobRun.idempotency_key is String(120)
    assert k != idempotency.ledger_key(T2, "plans.approve", "client-key-123")
    assert k != idempotency.ledger_key(T1, "projects.create", "client-key-123")


def test_request_hash_ignores_key_order() -> None:
    assert idempotency.request_hash({"a": 1, "b": [1, 2]}) == \
        idempotency.request_hash({"b": [1, 2], "a": 1})
    assert idempotency.request_hash({"a": 1}) != idempotency.request_hash({"a": 2})


def test_no_header_is_a_no_op(db: _FakeSession) -> None:
    idem, _ = _begin(db, None, {"x": 1})
    assert not idem.replayed
    idem.store(201, {"ok": True})
    assert db.rows == {}


def test_first_request_claims_then_retry_replays_stored_response(db: _FakeSession) -> None:
    idem, _ = _begin(db, "k1", {"plan": "p"})
    assert not idem.replayed
    (row,) = db.rows.values()
    assert row.status == "running"
    assert row.tenant_id == T1
    assert row.job_type == "api.plans.approve"
    idem.store(201, {"plan_id": "p", "decision": "approved"})
    assert row.status == "succeeded"

    again, resp = _begin(db, "k1", {"plan": "p"})
    assert again.replayed
    assert again.body == {"plan_id": "p", "decision": "approved"}
    assert resp.status_code == 201
    assert resp.headers[idempotency.REPLAYED_HEADER] == "true"
    assert len(db.rows) == 1


def test_same_key_different_request_is_422(db: _FakeSession) -> None:
    idem, _ = _begin(db, "k1", {"plan": "p"})
    idem.store(201, {})
    with pytest.raises(HTTPException) as exc:
        _begin(db, "k1", {"plan": "OTHER"})
    assert exc.value.status_code == 422


def test_same_key_still_running_is_409(db: _FakeSession) -> None:
    _begin(db, "k1", {"plan": "p"})  # claimed, never stored
    with pytest.raises(HTTPException) as exc:
        _begin(db, "k1", {"plan": "p"})
    assert exc.value.status_code == 409


def test_same_client_key_in_another_tenant_is_independent(db: _FakeSession) -> None:
    idem, _ = _begin(db, "k1", {"plan": "p"})
    idem.store(201, {"t": 1})
    other, _ = _begin(db, "k1", {"plan": "p"}, tenant=T2)
    assert not other.replayed
    assert len(db.rows) == 2
