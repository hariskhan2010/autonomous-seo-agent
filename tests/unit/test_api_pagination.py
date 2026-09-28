"""Cursor pagination helper + its wiring into a list endpoint (Phase 12 deferral) — no DB: the
endpoint test swaps `get_db` for a fake session that returns canned rows."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterator
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from app.deps import get_db
from app.main import app
from app.pagination import (
    DEFAULT_LIMIT,
    apply_keyset,
    decode_cursor,
    effective_limit,
    encode_cursor,
    finish_page,
)
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from db.models.opportunity import Opportunity


def test_cursor_round_trips_every_supported_type() -> None:
    vals = [dt.datetime(2026, 9, 1, 12, 30, 5, 123456, tzinfo=dt.UTC), dt.date(2026, 9, 1),
            Decimal("0.875"), uuid.uuid4(), 42, 1.5, "x"]
    assert decode_cursor(encode_cursor("s", vals), scope="s", arity=len(vals)) == vals


@pytest.mark.parametrize("cursor", ["", "!!!", "bm90LWpzb24", encode_cursor("other", [1, 2])])
def test_bad_or_foreign_cursor_is_400(cursor: str) -> None:
    with pytest.raises(HTTPException) as exc:
        decode_cursor(cursor, scope="mine", arity=2)
    assert exc.value.status_code == 400


def test_wrong_arity_cursor_is_400() -> None:
    with pytest.raises(HTTPException):
        decode_cursor(encode_cursor("s", [1]), scope="s", arity=2)


def test_effective_limit_keeps_legacy_unpaginated_default() -> None:
    assert effective_limit(None, None) is None
    assert effective_limit(None, "c") == DEFAULT_LIMIT
    assert effective_limit(7, None) == 7


def test_finish_page_trims_probe_row_and_mints_cursor_from_last_kept_row() -> None:
    rows = [(3, "c"), (2, "b"), (1, "a")]
    page, nxt = finish_page(rows, scope="s", limit=2, key_of=lambda r: [r[0], r[1]])
    assert page == [(3, "c"), (2, "b")]
    assert nxt is not None
    assert decode_cursor(nxt, scope="s", arity=2) == [2, "b"]
    assert finish_page(rows, scope="s", limit=3, key_of=lambda r: [r[0]]) == (rows, None)
    assert finish_page(rows, scope="s", limit=None, key_of=lambda r: [r[0]]) == (rows, None)


def test_apply_keyset_orders_desc_with_row_comparison_and_probe_limit() -> None:
    oid = uuid.uuid4()
    stmt = apply_keyset(select(Opportunity), (Opportunity.score, Opportunity.id), scope="o",
                        cursor=encode_cursor("o", [Decimal("5.5"), oid]), limit=10)
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "(opportunities.score, opportunities.id) < (" in sql
    assert "ORDER BY opportunities.score DESC, opportunities.id DESC" in sql
    params = stmt.compile(dialect=postgresql.dialect()).params
    assert 11 in params.values()  # limit + 1 probe row
    assert oid in params.values()


def test_apply_keyset_without_cursor_or_limit_is_the_legacy_query() -> None:
    sql = str(apply_keyset(select(Opportunity), (Opportunity.score, Opportunity.id), scope="o",
                           cursor=None, limit=None).compile(dialect=postgresql.dialect()))
    assert "LIMIT" not in sql
    assert " < " not in sql


# ── endpoint wiring (fake session) ──

def _anomaly(i: int) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.UUID(int=i), metric="clicks", direction="down",
                           magnitude_pct=Decimal("12.5"), detected_on=dt.date(2026, 9, i),
                           investigation={})


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows
        self.statements: list[Any] = []

    def execute(self, stmt: Any) -> _FakeResult:
        self.statements.append(stmt)
        limit = stmt._limit_clause.value if stmt._limit_clause is not None else None
        return _FakeResult(self.rows if limit is None else self.rows[:limit])


@pytest.fixture
def fake_db() -> Iterator[_FakeSession]:
    fake = _FakeSession([_anomaly(i) for i in (5, 4, 3)])

    def _override() -> Iterator[_FakeSession]:
        yield fake

    app.dependency_overrides[get_db] = _override
    try:
        yield fake
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_list_without_params_is_unchanged_bare_array_and_no_cursor(fake_db: _FakeSession) -> None:
    r = TestClient(app).get("/v1/anomalies")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) == 3
    assert "x-next-cursor" not in r.headers


def test_list_with_limit_returns_page_and_next_cursor_headers(fake_db: _FakeSession) -> None:
    r = TestClient(app).get("/v1/anomalies?limit=2")
    assert r.status_code == 200
    body = r.json()
    assert [a["detected_on"] for a in body] == ["2026-09-05", "2026-09-04"]
    nxt = r.headers["x-next-cursor"]
    assert decode_cursor(nxt, scope="anomalies", arity=2) == [dt.date(2026, 9, 4),
                                                              uuid.UUID(int=4)]
    assert r.headers["link"].endswith('rel="next"')
    assert f"cursor={nxt}" in r.headers["link"]


def test_list_rejects_out_of_range_limit_and_foreign_cursor(fake_db: _FakeSession) -> None:
    c = TestClient(app)
    assert c.get("/v1/anomalies?limit=0").status_code == 422
    assert c.get("/v1/anomalies?limit=1000").status_code == 422
    assert c.get(f"/v1/anomalies?cursor={encode_cursor('changes', [1, 2])}").status_code == 400


def test_keywords_body_gains_next_cursor_field(fake_db: _FakeSession) -> None:
    fake_db.rows = [SimpleNamespace(id=uuid.UUID(int=i), name=f"c{i}", size=1, volume_sum=10 * i,
                                    primary_intent="info", intents={}) for i in (3, 2, 1)]
    body = TestClient(app).get("/v1/keywords?limit=2").json()
    assert set(body) == {"count", "clusters", "next_cursor"}
    assert [c["name"] for c in body["clusters"]] == ["c3", "c2"]
    assert body["next_cursor"] is not None
