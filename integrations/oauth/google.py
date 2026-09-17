"""Google OAuth 2.0 (Phase 9/12/13) — the token-exchange half of what `GscProvider`/`Ga4Provider`
already assume exists: a real per-project refresh token, obtained through a real consent flow
rather than a bare app-wide `Settings` field (see `integrations/analytics/base.py`
`get_metrics_provider`'s docstring for why it isn't one).

Real HTTP calls against Google's own endpoints, no Google SDK dependency — matches this
codebase's httpx-first style elsewhere (`integrations/analytics/{gsc,ga4}.py`).

`build_oauth_state` / `verify_oauth_state` are the CSRF defense for the callback endpoint: Google
redirects the user's browser there directly, with no bearer token to authenticate the request, so
the signed `state` round-tripped through Google is the only thing proving which tenant/project/user
actually started this flow."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from common.settings import settings

_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105 - a URL, not a secret
_USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v3/userinfo"
_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"  # noqa: S105 - a URL, not a secret

SCOPES = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/analytics.readonly",
)

_STATE_PURPOSE = "google_oauth"
_STATE_TTL_SECONDS = 600  # the whole consent round trip must complete within 10 minutes
UTC = dt.UTC


class GoogleOAuthError(RuntimeError):
    pass


class InvalidOAuthState(GoogleOAuthError):
    pass


@dataclass(frozen=True)
class OAuthState:
    tenant_id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID


def build_oauth_state(*, tenant_id: uuid.UUID, project_id: uuid.UUID, user_id: uuid.UUID) -> str:
    now = dt.datetime.now(UTC)
    claims = {
        "purpose": _STATE_PURPOSE, "tenant_id": str(tenant_id), "project_id": str(project_id),
        "user_id": str(user_id), "iat": now,
        "exp": now + dt.timedelta(seconds=_STATE_TTL_SECONDS),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


def verify_oauth_state(state: str) -> OAuthState:
    try:
        claims = jwt.decode(state, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise InvalidOAuthState(f"invalid or expired oauth state: {exc}") from exc
    if claims.get("purpose") != _STATE_PURPOSE:
        raise InvalidOAuthState("oauth state was not issued for this flow")
    try:
        return OAuthState(
            tenant_id=uuid.UUID(claims["tenant_id"]), project_id=uuid.UUID(claims["project_id"]),
            user_id=uuid.UUID(claims["user_id"]),
        )
    except (KeyError, ValueError) as exc:
        raise InvalidOAuthState(f"oauth state missing/invalid claims: {exc}") from exc


def build_authorization_url(*, state: str) -> str:
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",  # required to receive a refresh_token, not just an access_token
        "prompt": "consent",       # forces a fresh refresh_token even on a repeat connect
        "state": state,
    }
    return f"{_AUTH_ENDPOINT}?{urlencode(params)}"


def exchange_code_for_tokens(code: str) -> dict[str, Any]:
    resp = httpx.post(_TOKEN_ENDPOINT, data={
        "code": code, "client_id": settings.google_oauth_client_id,
        "client_secret": settings.google_oauth_client_secret,
        "redirect_uri": settings.google_oauth_redirect_uri, "grant_type": "authorization_code",
    }, timeout=30)
    resp.raise_for_status()
    return dict(resp.json())


def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    resp = httpx.post(_TOKEN_ENDPOINT, data={
        "client_id": settings.google_oauth_client_id,
        "client_secret": settings.google_oauth_client_secret,
        "refresh_token": refresh_token, "grant_type": "refresh_token",
    }, timeout=30)
    resp.raise_for_status()
    return dict(resp.json())


def fetch_account_email(access_token: str) -> str:
    resp = httpx.get(
        _USERINFO_ENDPOINT, headers={"Authorization": f"Bearer {access_token}"}, timeout=15,
    )
    resp.raise_for_status()
    email = resp.json().get("email")
    if not email:
        raise GoogleOAuthError("Google userinfo response had no email claim")
    return str(email)


def revoke_token(token: str) -> None:
    """Best-effort — Google's own server-side revoke. A failure here must never block the local
    revoke (`OAuthCredential.revoked_at`), which is the actual security boundary: once no active
    row exists, nothing looks the token up again regardless of whether Google's own copy of it is
    still technically alive."""
    try:
        httpx.post(_REVOKE_ENDPOINT, params={"token": token}, timeout=15)
    except httpx.HTTPError:
        pass
