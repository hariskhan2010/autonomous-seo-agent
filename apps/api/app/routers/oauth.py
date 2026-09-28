"""Google OAuth connect/status/revoke (Phase 9/12/13) — closes the credential-storage gap
`GscProvider`/`Ga4Provider` (`integrations/analytics/{gsc,ga4}.py`) were built expecting: a real,
per-project refresh token has to come from somewhere.

`/oauth/google/callback` is the one route in this file with no bearer token — Google redirects the
user's browser here directly, so the signed `state` round-tripped through the whole consent flow
(`integrations/oauth/google.py`) is the only thing authenticating the request; it is verified
before anything else happens, together with the `/start`-issued nonce cookie that binds it to the
initiating browser. That means the BROWSER must call `/start` (a `fetch(..., {credentials:
"include"})` or navigation to the API origin) — a server-side call would drop the cookie and the
callback would then refuse the flow."""

from __future__ import annotations

import datetime as dt
import uuid
from urllib.parse import urlparse

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from integrations.oauth import google as google_oauth
from sqlalchemy.orm import Session

from app.auth import Principal
from app.deps import get_db, require_project, require_role
from app.schemas import OAuthConfigUpdate, OAuthStartOut, OAuthStatusOut
from common.crypto import decrypt_secret, encrypt_secret
from common.settings import settings
from db.models.credential import OAuthCredential
from db.session import tenant_session

router = APIRouter(tags=["oauth"])
log = structlog.get_logger("api.oauth")
UTC = dt.UTC
NONCE_COOKIE = "seo_oauth_nonce"


def _nonce_cookie_path() -> str:
    # Scoped to the callback route only — the nonce is never sent anywhere else.
    return urlparse(settings.google_oauth_redirect_uri).path or "/"


def _active_credential(db: Session, project_id: uuid.UUID) -> OAuthCredential | None:
    return db.query(OAuthCredential).filter(
        OAuthCredential.project_id == project_id, OAuthCredential.provider == "google",
        OAuthCredential.revoked_at.is_(None),
    ).order_by(OAuthCredential.connected_at.desc()).first()


@router.get("/projects/{project_id}/oauth/google/start", response_model=OAuthStartOut)
def start_google_oauth(
    response: Response,
    project_id: uuid.UUID = Depends(require_project),
    principal: Principal = Depends(require_role("operator")),
) -> OAuthStartOut:
    nonce = google_oauth.new_state_nonce()
    state = google_oauth.build_oauth_state(
        tenant_id=principal.tenant_id, project_id=project_id, user_id=principal.user_id,
        nonce=nonce,
    )
    response.set_cookie(
        NONCE_COOKIE, nonce, max_age=google_oauth.STATE_TTL_SECONDS, path=_nonce_cookie_path(),
        httponly=True, samesite="lax",  # Lax still rides along on Google's top-level redirect back
        secure=settings.env not in ("dev", "test"),  # dev runs on plain http://localhost
    )
    return OAuthStartOut(authorization_url=google_oauth.build_authorization_url(state=state))


@router.get("/oauth/google/callback")
def google_oauth_callback(
    request: Request, response: Response,
    code: str | None = Query(default=None), state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> dict[str, object]:
    if error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Google returned an error: {error}")
    if not code or not state:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "missing code or state")

    try:
        parsed_state = google_oauth.verify_oauth_state(
            state, nonce=request.cookies.get(NONCE_COOKIE)
        )
    except google_oauth.InvalidOAuthState as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    # Single use: cleared on success. (If a later step raises, FastAPI drops this header, and the
    # cookie simply expires with the state; Google's `code` is single-use regardless.)
    response.delete_cookie(NONCE_COOKIE, path=_nonce_cookie_path())

    try:
        tokens = google_oauth.exchange_code_for_tokens(code)
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller as a clear 400, not a 500
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"token exchange failed: {exc}") from exc

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        # Google omits this when the account already granted offline access and `prompt=consent`
        # wasn't (for some reason) honored — surfaced clearly rather than silently storing nothing.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Google did not return a refresh token — try disconnecting this app's access at "
            "https://myaccount.google.com/permissions and reconnecting",
        )
    account_email = google_oauth.fetch_account_email(str(tokens["access_token"]))
    granted_scopes = str(tokens.get("scope", "")).split()

    now = dt.datetime.now(UTC)
    with tenant_session(parsed_state.tenant_id, parsed_state.project_id) as s:
        existing = _active_credential(s, parsed_state.project_id)
        if existing is not None:
            existing.revoked_at = now
            existing.revoked_by = parsed_state.user_id

        s.add(OAuthCredential(
            tenant_id=parsed_state.tenant_id, project_id=parsed_state.project_id,
            provider="google", account_email=account_email, scopes=granted_scopes,
            encrypted_refresh_token=encrypt_secret(str(refresh_token)),
            connected_by=parsed_state.user_id, connected_at=now,
        ))

    log.info("oauth.google.connected", project_id=str(parsed_state.project_id),
             account_email=account_email)
    return {"connected": True, "account_email": account_email}


@router.get("/projects/{project_id}/oauth/google/status", response_model=OAuthStatusOut)
def google_oauth_status(
    project_id: uuid.UUID = Depends(require_project), db: Session = Depends(get_db),
) -> OAuthStatusOut:
    active = _active_credential(db, project_id)
    if active is None:
        return OAuthStatusOut(connected=False)
    return OAuthStatusOut(
        connected=True, account_email=active.account_email, connected_at=active.connected_at,
    )


@router.post("/projects/{project_id}/oauth/google/revoke", response_model=OAuthStatusOut)
def revoke_google_oauth(
    project_id: uuid.UUID = Depends(require_project),
    principal: Principal = Depends(require_role("operator")),
    db: Session = Depends(get_db),
) -> OAuthStatusOut:
    active = _active_credential(db, project_id)
    if active is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "no active Google connection for this project")

    google_oauth.revoke_token(decrypt_secret(active.encrypted_refresh_token))
    now = dt.datetime.now(UTC)
    active.revoked_at = now
    active.revoked_by = principal.user_id
    return OAuthStatusOut(
        connected=False, account_email=active.account_email, connected_at=active.connected_at,
        revoked_at=now,
    )


@router.patch("/projects/{project_id}/oauth/google/config", response_model=OAuthStatusOut)
def update_google_oauth_config(
    body: OAuthConfigUpdate,
    project_id: uuid.UUID = Depends(require_project),
    _principal: Principal = Depends(require_role("operator")),
    db: Session = Depends(get_db),
) -> OAuthStatusOut:
    active = _active_credential(db, project_id)
    if active is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "no active Google connection for this project")

    updates = body.model_dump(exclude_unset=True, exclude_none=True)
    active.provider_meta = {**active.provider_meta, **updates}
    return OAuthStatusOut(
        connected=True, account_email=active.account_email, connected_at=active.connected_at,
    )
