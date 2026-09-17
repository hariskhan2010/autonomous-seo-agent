"""Engine + tenant-scoped sessions (A-TO-Z-PLAN.md §F.2).

The API request path and the worker job path both call `tenant_session(tenant_id, project_id)`,
which opens a transaction as the NOBYPASSRLS `seo_app` role and issues
`SET LOCAL app.tenant_id / app.project_id` before any query. RLS does the rest.

A session with no tenant context is only for migrations/tests and must not serve requests."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from common.settings import settings

_engine: Engine | None = None
_Session: sessionmaker[Session] | None = None


def engine() -> Engine:
    global _engine, _Session
    if _engine is None:
        _engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            future=True,
        )
        _Session = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def _sessionmaker() -> sessionmaker[Session]:
    engine()
    assert _Session is not None
    return _Session


@contextmanager
def tenant_session(
    tenant_id: uuid.UUID | str, project_id: uuid.UUID | str | None = None
) -> Iterator[Session]:
    """Transactional session bound to one tenant (and optionally one project). Commits on
    success, rolls back on error. GUCs are LOCAL — they vanish with the transaction."""
    session = _sessionmaker()()
    try:
        session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        session.execute(
            text("SELECT set_config('app.project_id', :p, true)"),
            {"p": "" if project_id is None else str(project_id)},
        )
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def get_session() -> Iterator[Session]:
    """Unscoped session — migrations, seed, and tests only. RLS still applies under `seo_app`."""
    session = _sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@event.listens_for(Engine, "connect")
def _set_search_path(dbapi_conn: object, _rec: object) -> None:
    cur = dbapi_conn.cursor()  # type: ignore[attr-defined]
    cur.execute("SET search_path TO public")
    cur.close()
