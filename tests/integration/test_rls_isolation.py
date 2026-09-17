"""The cross-tenant isolation test (A-TO-Z-PLAN.md §Phase 1 acceptance, §U.5).

This test guards every later phase. It exercises the real request path: a tenant-scoped session
opened as the NOBYPASSRLS `seo_app` role with `SET LOCAL app.tenant_id`."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from db.models.identity import Tenant
from db.models.project import Project
from db.session import tenant_session


@pytest.fixture
def two_tenants() -> tuple[uuid.UUID, uuid.UUID]:
    a, b = uuid.uuid4(), uuid.uuid4()
    with tenant_session(a) as s:
        s.add(Tenant(id=a, name="Tenant A", slug=f"a-{a.hex[:8]}"))
        s.add(Project(tenant_id=a, name="A project", slug="p", approval_mode="read_only"))
    with tenant_session(b) as s:
        s.add(Tenant(id=b, name="Tenant B", slug=f"b-{b.hex[:8]}"))
        s.add(Project(tenant_id=b, name="B project", slug="p", approval_mode="read_only"))
    yield a, b
    for t in (a, b):
        with tenant_session(t) as s:
            s.query(Project).delete()
            s.query(Tenant).delete()


def test_tenant_sees_only_its_own_rows(two_tenants: tuple[uuid.UUID, uuid.UUID]) -> None:
    a, b = two_tenants
    with tenant_session(a) as s:
        rows = s.execute(select(Project)).scalars().all()
        assert [p.tenant_id for p in rows] == [a]
    with tenant_session(b) as s:
        rows = s.execute(select(Project)).scalars().all()
        assert [p.tenant_id for p in rows] == [b]


def test_tenant_cannot_read_other_tenant_by_id(two_tenants: tuple[uuid.UUID, uuid.UUID]) -> None:
    a, b = two_tenants
    with tenant_session(b) as s:
        got = s.get(Tenant, a)
        assert got is None


def test_with_check_blocks_cross_tenant_insert(two_tenants: tuple[uuid.UUID, uuid.UUID]) -> None:
    a, b = two_tenants
    with pytest.raises(DBAPIError), tenant_session(b) as s:
        s.add(Project(tenant_id=a, name="smuggled", slug="x", approval_mode="read_only"))
        s.flush()


def test_runtime_role_cannot_bypass_rls() -> None:
    """`seo_app` must be NOBYPASSRLS — the guard against Neon's neondb_owner having BYPASSRLS."""
    with tenant_session(uuid.uuid4()) as s:
        bypass = s.execute(
            text("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).scalar_one()
        assert bypass is False
