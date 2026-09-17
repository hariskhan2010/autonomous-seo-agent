"""`integrations/oauth/google.py` (Phase 9/12/13) — no real Google credentials, no network:
`httpx.post`/`httpx.get` are monkeypatched with a tiny fake response. State-token CSRF defense is
exercised for real (`jwt.encode`/`decode`, no mocking needed there)."""

from __future__ import annotations

import datetime as dt
import uuid

import httpx
import jwt
import pytest
from integrations.oauth.google import (
    GoogleOAuthError,
    InvalidOAuthState,
    build_authorization_url,
    build_oauth_state,
    exchange_code_for_tokens,
    fetch_account_email,
    refresh_access_token,
    revoke_token,
    verify_oauth_state,
)

from common.settings import settings

UTC = dt.UTC


class _FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> object:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=httpx.Request("POST", "https://x"),
                                        response=httpx.Response(self.status_code))


# ── OAuth state (CSRF defense) ──


def test_state_round_trips() -> None:
    t, p, u = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    state = build_oauth_state(tenant_id=t, project_id=p, user_id=u)
    parsed = verify_oauth_state(state)
    assert (parsed.tenant_id, parsed.project_id, parsed.user_id) == (t, p, u)


def test_tampered_state_is_rejected() -> None:
    state = build_oauth_state(tenant_id=uuid.uuid4(), project_id=uuid.uuid4(), user_id=uuid.uuid4())
    with pytest.raises(InvalidOAuthState):
        verify_oauth_state(state + "x")


def test_expired_state_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    past = dt.datetime.now(UTC) - dt.timedelta(seconds=700)
    state = jwt.encode(
        {"purpose": "google_oauth", "tenant_id": str(uuid.uuid4()), "project_id": str(uuid.uuid4()),
         "user_id": str(uuid.uuid4()), "iat": past, "exp": past + dt.timedelta(seconds=600)},
        settings.jwt_secret, algorithm="HS256",
    )
    with pytest.raises(InvalidOAuthState):
        verify_oauth_state(state)


def test_state_from_a_different_purpose_is_rejected() -> None:
    state = jwt.encode(
        {"purpose": "something_else", "tenant_id": str(uuid.uuid4()),
         "project_id": str(uuid.uuid4()), "user_id": str(uuid.uuid4())},
        settings.jwt_secret, algorithm="HS256",
    )
    with pytest.raises(InvalidOAuthState, match="not issued for this flow"):
        verify_oauth_state(state)


def test_authorization_url_requests_offline_access_and_carries_state() -> None:
    url = build_authorization_url(state="opaque-state-value")
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=opaque-state-value" in url


# ── HTTP calls (fake responses, no network) ──


def test_exchange_code_for_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, *, data: dict[str, object], timeout: float) -> _FakeResponse:
        captured["url"], captured["data"] = url, data
        return _FakeResponse(200, {"access_token": "a", "refresh_token": "r", "expires_in": 3600})

    monkeypatch.setattr(httpx, "post", fake_post)
    out = exchange_code_for_tokens("the-code")
    assert out["refresh_token"] == "r"
    assert captured["data"]["code"] == "the-code"  # type: ignore[index]
    assert captured["data"]["grant_type"] == "authorization_code"  # type: ignore[index]


def test_refresh_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx, "post",
        lambda url, *, data, timeout: _FakeResponse(200, {"access_token": "fresh", "expires_in": 3600}),
    )
    out = refresh_access_token("stored-refresh-token")
    assert out["access_token"] == "fresh"


def test_token_endpoint_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx, "post", lambda url, *, data, timeout: _FakeResponse(400, {"error": "invalid_grant"}),
    )
    with pytest.raises(httpx.HTTPStatusError):
        refresh_access_token("a-revoked-token")


def test_fetch_account_email(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx, "get", lambda url, *, headers, timeout: _FakeResponse(200, {"email": "me@example.com"}),
    )
    assert fetch_account_email("access-token") == "me@example.com"


def test_fetch_account_email_raises_without_an_email_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda url, *, headers, timeout: _FakeResponse(200, {}))
    with pytest.raises(GoogleOAuthError, match="no email claim"):
        fetch_account_email("access-token")


def test_revoke_is_best_effort_and_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(url: str, *, params: dict[str, object], timeout: float) -> None:
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(httpx, "post", _boom)
    revoke_token("some-token")  # must not raise
