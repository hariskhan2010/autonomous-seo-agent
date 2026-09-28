"""Keyset (cursor) pagination for the list endpoints (docs/API.md "Pagination", Phase 12).

Backward compatible by construction: the list endpoints keep returning a bare JSON array, and
the cursor for the next page travels in the `X-Next-Cursor` response header (plus an RFC 8288
`Link: <...>; rel="next"`). A client that never sends `limit`/`cursor` sees exactly the response
it always did; `/keywords`, whose body is already an object, also gets a `next_cursor` field.

Keyset, not OFFSET: each endpoint orders by `(sort_key DESC, id DESC)` and the cursor encodes the
last row's `(sort_key, id)`, so the next page is `WHERE (sort_key, id) < (:k, :id)` — stable under
concurrent inserts and index-friendly. The cursor is opaque (urlsafe base64 JSON) and carries a
`scope` so a cursor minted by one endpoint is rejected (400) by another instead of silently
comparing unrelated columns."""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import json
import uuid
from collections.abc import Callable, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, Request, Response, status
from sqlalchemy import Select, literal, tuple_
from sqlalchemy.orm import InstrumentedAttribute, Session

MAX_LIMIT = 200
# Applied only when a client sends `cursor` without `limit` — i.e. a client that is already
# paging. A request with neither keeps the legacy unpaginated behaviour.
DEFAULT_LIMIT = 50

_Scalar = dt.datetime | dt.date | Decimal | uuid.UUID | int | float | str


def _tag(v: _Scalar) -> list[str]:
    # datetime before date: datetime is a date subclass.
    if isinstance(v, dt.datetime):
        return ["dt", v.isoformat()]
    if isinstance(v, dt.date):
        return ["d", v.isoformat()]
    if isinstance(v, Decimal):
        return ["dec", str(v)]
    if isinstance(v, uuid.UUID):
        return ["u", str(v)]
    if isinstance(v, bool):  # bool is an int subclass — never a valid sort key here
        raise TypeError("bool is not a supported cursor value")
    if isinstance(v, int):
        return ["i", str(v)]
    if isinstance(v, float):
        return ["f", repr(v)]
    if isinstance(v, str):
        return ["s", v]
    raise TypeError(f"unsupported cursor value type: {type(v).__name__}")


_UNTAG: dict[str, Callable[[str], _Scalar]] = {
    "dt": dt.datetime.fromisoformat, "d": dt.date.fromisoformat, "dec": Decimal,
    "u": uuid.UUID, "i": int, "f": float, "s": str,
}


def _bad_cursor() -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, "invalid cursor")


def encode_cursor(scope: str, values: Sequence[_Scalar]) -> str:
    raw = json.dumps({"s": scope, "v": [_tag(v) for v in values]}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, *, scope: str, arity: int) -> list[_Scalar]:
    """Inverse of `encode_cursor`. Any malformed / foreign-scope / wrong-arity cursor -> 400."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        doc = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        if not isinstance(doc, dict) or doc.get("s") != scope:
            raise _bad_cursor()
        vals = doc.get("v")
        if not isinstance(vals, list) or len(vals) != arity:
            raise _bad_cursor()
        return [_UNTAG[tag](text) for tag, text in vals]
    except HTTPException:
        raise
    except (ValueError, TypeError, KeyError, InvalidOperation, binascii.Error,
            UnicodeDecodeError):
        raise _bad_cursor() from None


def apply_keyset(
    stmt: Select[Any], keys: Sequence[InstrumentedAttribute[Any]], *, scope: str,
    cursor: str | None, limit: int | None,
) -> Select[Any]:
    """Orders `stmt` by `keys` (all DESC — the last key must be the unique tiebreak, i.e. `id`),
    applies the after-cursor predicate, and fetches `limit + 1` rows so `finish_page` can tell
    whether another page exists. `limit=None` and no cursor = the legacy unpaginated listing."""
    stmt = stmt.order_by(*(k.desc() for k in keys))
    if cursor is not None:
        vals = decode_cursor(cursor, scope=scope, arity=len(keys))
        bound = (literal(v, k.type) for k, v in zip(keys, vals, strict=True))
        stmt = stmt.where(tuple_(*keys) < tuple_(*bound))
    if limit is not None:
        stmt = stmt.limit(limit + 1)
    return stmt


def finish_page[T](
    rows: Sequence[T], *, scope: str, limit: int | None, key_of: Callable[[T], Sequence[_Scalar]],
) -> tuple[list[T], str | None]:
    """Trims the `limit + 1` probe row; returns `(page_rows, next_cursor | None)`."""
    if limit is None or len(rows) <= limit:
        return list(rows), None
    page = list(rows[:limit])
    return page, encode_cursor(scope, key_of(page[-1]))


def set_next_headers(request: Request, response: Response, next_cursor: str | None) -> None:
    if next_cursor is None:
        return
    response.headers["X-Next-Cursor"] = next_cursor
    nxt = request.url.include_query_params(cursor=next_cursor)
    response.headers["Link"] = f'<{nxt}>; rel="next"'


def effective_limit(limit: int | None, cursor: str | None) -> int | None:
    if limit is not None:
        return limit
    return DEFAULT_LIMIT if cursor is not None else None


def paginate(
    db: Session, request: Request, response: Response, stmt: Select[Any],
    keys: Sequence[InstrumentedAttribute[Any]], *, scope: str, cursor: str | None,
    limit: int | None,
) -> list[Any]:
    """The whole round trip for a `select(Model)` listing: order + keyset + fetch + trim +
    `X-Next-Cursor`/`Link` headers. Returns the ORM rows for the page."""
    lim = effective_limit(limit, cursor)
    stmt = apply_keyset(stmt, keys, scope=scope, cursor=cursor, limit=lim)
    rows = db.execute(stmt).scalars().all()
    names = [k.key for k in keys]
    page, nxt = finish_page(rows, scope=scope, limit=lim,
                            key_of=lambda r: [getattr(r, n) for n in names])
    set_next_headers(request, response, nxt)
    return page
