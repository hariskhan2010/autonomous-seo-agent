"""Google OAuth connect/status/revoke over HTTP (Phase 9/12/13). No real Google credentials, no
network — `integrations.oauth.google`'s HTTP-calling functions are monkeypatched; the state-token
CSRF flow and the encrypted-storage round trip are exercised for real."""

from __future__ import annotations

import uuid

import integrations.oauth.google as google_oauth
import pytest
from app.main import app
from fastapi.testclient import TestClient

from db.models.credential import OAuthCredential
from db.models.identity import Tenant
from db.models.project import Project
from db.session import tenant_session

client = TestClient(app)


def _headers(tenant: uuid.UUID, user: uuid.UUID, role: str = "owner") -> dict[str, str]:
    return {"x-dev-tenant": str(tenant), "x-dev-user": str(user), "x-dev-role": role}


@pytest.fixture
def project() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    t, u = uuid.uuid4(), uuid.uuid4()
    with tenant_session(t) as s:
        s.add(Tenant(id=t, name="T", slug=f"t-{t.hex[:8]}"))
        proj = Project(tenant_id=t, name="Acme", slug=f"acme-{t.hex[:8]}")
        s.add(proj)
        s.flush()
        pid = proj.id
    yield t, u, pid
    with tenant_session(t) as s:
        s.query(OAuthCredential).delete()
        s.query(Project).delete()
        s.query(Tenant).delete()


def test_start_returns_an_authorization_url_with_a_valid_state(
    project: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    t, u, pid = project
    r = client.get(f"/v1/projects/{pid}/oauth/google/start", headers=_headers(t, u))
    assert r.status_code == 200, r.text
    url = r.json()["authorization_url"]
    assert "access_type=offline" in url
    assert "state=" in url


def test_start_requires_operator_role(
    project: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    t, u, pid = project
    r = client.get(
        f"/v1/projects/{pid}/oauth/google/start", headers=_headers(t, u, role="viewer"),
    )
    assert r.status_code == 403


def test_status_is_disconnected_before_connecting(
    project: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    t, u, pid = project
    r = client.get(f"/v1/projects/{pid}/oauth/google/status", headers=_headers(t, u))
    assert r.status_code == 200
    assert r.json() == {
        "connected": False, "account_email": None, "connected_at": None, "revoked_at": None,
    }


def test_callback_rejects_a_tampered_state() -> None:
    r = client.get("/v1/oauth/google/callback", params={"code": "abc", "state": "not-a-real-state"})
    assert r.status_code == 400


def test_callback_surfaces_googles_own_error_param() -> None:
    r = client.get("/v1/oauth/google/callback", params={"error": "access_denied"})
    assert r.status_code == 400
    assert "access_denied" in r.text


def test_full_connect_status_revoke_cycle(
    project: tuple[uuid.UUID, uuid.UUID, uuid.UUID], monkeypatch: pytest.MonkeyPatch,
) -> None:
    t, u, pid = project

    def fake_exchange(code: str) -> dict[str, object]:
        assert code == "the-auth-code"
        return {"access_token": "a-token", "refresh_token": "r-token-secret",
                "scope": "openid email https://www.googleapis.com/auth/webmasters.readonly"}

    monkeypatch.setattr(google_oauth, "exchange_code_for_tokens", fake_exchange)
    monkeypatch.setattr(google_oauth, "fetch_account_email", lambda token: "me@example.com")
    revoke_calls: list[str] = []
    monkeypatch.setattr(google_oauth, "revoke_token", lambda token: revoke_calls.append(token))

    state = google_oauth.build_oauth_state(tenant_id=t, project_id=pid, user_id=u)
    cb = client.get("/v1/oauth/google/callback", params={"code": "the-auth-code", "state": state})
    assert cb.status_code == 200, cb.text
    assert cb.json()["account_email"] == "me@example.com"

    status = client.get(f"/v1/projects/{pid}/oauth/google/status", headers=_headers(t, u))
    assert status.json()["connected"] is True
    assert status.json()["account_email"] == "me@example.com"

    # the encrypted refresh token is never exposed, and it's genuinely encrypted at rest.
    with tenant_session(t, pid) as s:
        row = s.query(OAuthCredential).filter(OAuthCredential.project_id == pid).one()
        assert row.encrypted_refresh_token != "r-token-secret"
        assert "webmasters.readonly" in row.scopes[-1]

    revoke = client.post(f"/v1/projects/{pid}/oauth/google/revoke", headers=_headers(t, u))
    assert revoke.status_code == 200, revoke.text
    assert revoke.json()["connected"] is False
    assert revoke_calls == ["r-token-secret"]

    status_after = client.get(f"/v1/projects/{pid}/oauth/google/status", headers=_headers(t, u))
    assert status_after.json()["connected"] is False

    # revoking again with nothing active is rejected, not silently accepted
    again = client.post(f"/v1/projects/{pid}/oauth/google/revoke", headers=_headers(t, u))
    assert again.status_code == 409


def test_reconnecting_revokes_the_previous_row_and_both_persist(
    project: tuple[uuid.UUID, uuid.UUID, uuid.UUID], monkeypatch: pytest.MonkeyPatch,
) -> None:
    t, u, pid = project
    monkeypatch.setattr(google_oauth, "fetch_account_email", lambda token: "me@example.com")

    for i in range(2):
        monkeypatch.setattr(
            google_oauth, "exchange_code_for_tokens",
            lambda code, i=i: {"access_token": "a", "refresh_token": f"refresh-{i}", "scope": ""},
        )
        state = google_oauth.build_oauth_state(tenant_id=t, project_id=pid, user_id=u)
        r = client.get("/v1/oauth/google/callback", params={"code": "c", "state": state})
        assert r.status_code == 200, r.text

    with tenant_session(t, pid) as s:
        rows = s.query(OAuthCredential).all()
        assert len(rows) == 2
        revoked_flags = sorted(row.revoked_at is not None for row in rows)
        assert revoked_flags == [False, True]  # exactly one revoked, one still active


def test_config_update_sets_ga4_property_id(
    project: tuple[uuid.UUID, uuid.UUID, uuid.UUID], monkeypatch: pytest.MonkeyPatch,
) -> None:
    t, u, pid = project
    monkeypatch.setattr(
        google_oauth, "exchange_code_for_tokens",
        lambda code: {"access_token": "a", "refresh_token": "r", "scope": ""},
    )
    monkeypatch.setattr(google_oauth, "fetch_account_email", lambda token: "me@example.com")
    state = google_oauth.build_oauth_state(tenant_id=t, project_id=pid, user_id=u)
    client.get("/v1/oauth/google/callback", params={"code": "c", "state": state})

    r = client.patch(
        f"/v1/projects/{pid}/oauth/google/config", json={"ga4_property_id": "properties/123"},
        headers=_headers(t, u),
    )
    assert r.status_code == 200, r.text

    with tenant_session(t, pid) as s:
        row = s.query(OAuthCredential).filter(
            OAuthCredential.project_id == pid, OAuthCredential.revoked_at.is_(None),
        ).one()
        assert row.provider_meta["ga4_property_id"] == "properties/123"
