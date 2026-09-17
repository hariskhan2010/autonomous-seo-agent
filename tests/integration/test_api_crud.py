"""CRUD + auth + tenant-isolation over the HTTP surface (A-TO-Z-PLAN.md §Phase 1 acceptance)."""

from __future__ import annotations

import uuid

from app.main import app
from fastapi.testclient import TestClient

from db.models.identity import Tenant
from db.models.project import Project
from db.session import tenant_session

client = TestClient(app)


def _headers(tenant: uuid.UUID, user: uuid.UUID, role: str = "owner") -> dict[str, str]:
    return {"x-dev-tenant": str(tenant), "x-dev-user": str(user), "x-dev-role": role}


def test_unauthenticated_is_401() -> None:
    assert client.get("/v1/projects").status_code == 401


def test_create_and_read_project() -> None:
    t, u = uuid.uuid4(), uuid.uuid4()
    h = _headers(t, u)
    try:
        r = client.post("/v1/projects", json={"name": "Acme", "slug": "acme"}, headers=h)
        assert r.status_code == 201, r.text
        pid = r.json()["id"]

        assert client.get(f"/v1/projects/{pid}", headers=h).json()["slug"] == "acme"

        cfg = {"business_goal": "rank for gemstones", "competitors": ["x.com"]}
        assert client.put(f"/v1/projects/{pid}/config", json=cfg, headers=h).status_code == 200
        assert client.get(f"/v1/projects/{pid}/config", headers=h).json()["competitors"] == ["x.com"]
    finally:
        with tenant_session(t) as s:
            s.query(Project).delete()
            s.query(Tenant).delete()


def test_cross_tenant_project_is_invisible_over_http() -> None:
    ta, ua, tb, ub = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    try:
        r = client.post("/v1/projects", json={"name": "A", "slug": "a"}, headers=_headers(ta, ua))
        pid = r.json()["id"]
        # tenant B cannot see or fetch tenant A's project
        assert client.get("/v1/projects", headers=_headers(tb, ub)).json() == []
        assert client.get(f"/v1/projects/{pid}", headers=_headers(tb, ub)).status_code == 404
    finally:
        for t in (ta, tb):
            with tenant_session(t) as s:
                s.query(Project).delete()
                s.query(Tenant).delete()


def test_viewer_cannot_create() -> None:
    t, u = uuid.uuid4(), uuid.uuid4()
    r = client.post(
        "/v1/projects", json={"name": "N", "slug": "n"}, headers=_headers(t, u, role="viewer")
    )
    assert r.status_code == 403


def test_patch_approval_mode_is_the_kill_switch() -> None:
    """Phase 13 hardening: an operator must be able to stop a project from applying any new
    autonomous action without touching the database directly."""
    t, u = uuid.uuid4(), uuid.uuid4()
    h = _headers(t, u)
    try:
        r = client.post("/v1/projects", json={"name": "N", "slug": "n"}, headers=h)
        pid = r.json()["id"]
        assert r.json()["approval_mode"] == "read_only"

        patched = client.patch(
            f"/v1/projects/{pid}", json={"approval_mode": "assisted"}, headers=h,
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["approval_mode"] == "assisted"
        assert client.get(f"/v1/projects/{pid}", headers=h).json()["approval_mode"] == "assisted"

        # and back to read_only — the actual kill switch
        killed = client.patch(
            f"/v1/projects/{pid}", json={"approval_mode": "read_only"}, headers=h,
        )
        assert killed.json()["approval_mode"] == "read_only"
    finally:
        with tenant_session(t) as s:
            s.query(Project).delete()
            s.query(Tenant).delete()


def test_patch_requires_admin_role() -> None:
    t, u = uuid.uuid4(), uuid.uuid4()
    h = _headers(t, u)
    try:
        r = client.post("/v1/projects", json={"name": "N", "slug": "n"}, headers=h)
        pid = r.json()["id"]
        blocked = client.patch(
            f"/v1/projects/{pid}", json={"approval_mode": "autonomous"},
            headers=_headers(t, u, role="operator"),
        )
        assert blocked.status_code == 403
    finally:
        with tenant_session(t) as s:
            s.query(Project).delete()
            s.query(Tenant).delete()


def test_patch_with_no_fields_is_rejected() -> None:
    t, u = uuid.uuid4(), uuid.uuid4()
    h = _headers(t, u)
    try:
        r = client.post("/v1/projects", json={"name": "N", "slug": "n"}, headers=h)
        pid = r.json()["id"]
        assert client.patch(f"/v1/projects/{pid}", json={}, headers=h).status_code == 400
    finally:
        with tenant_session(t) as s:
            s.query(Project).delete()
            s.query(Tenant).delete()
