"""Per-project OAuth credentials (Phase 9/12) — closes the gap `GscProvider`/`Ga4Provider` left
open on purpose: a real refresh token has to come from *somewhere* per-project, encrypted at
rest, not a bare `Settings` field like the app-wide LLM keys (see `integrations/analytics/base.py`
`get_metrics_provider`'s docstring).

Connecting is always a NEW row, never a mutable flag flip — the same "logged, re-confirmable"
pattern as the sibling trading-agent project's `LiveTradingEnablement`: revoking and reconnecting
both leave a full audit trail rather than overwriting history. `encrypted_refresh_token` is
`packages/common/crypto.py` ciphertext and must never be returned by any API response.

Deliberately does NOT cache an access token: `GscProvider`/`Ga4Provider` already exchange the
refresh token for a fresh access token on every call (`integrations/analytics/{gsc,ga4}.py`) —
adding a second, unused caching layer here would be exactly the kind of premature complexity
nothing in this codebase actually reads yet."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, ProjectScopedMixin

OAUTH_PROVIDERS = ("google",)
# Built manually rather than via `OAUTH_PROVIDERS!r`: Python's repr of a one-element tuple is
# `('google',)` — valid Python, but the trailing comma makes it invalid SQL inside `IN (...)`.
_PROVIDERS_SQL_LIST = ", ".join(f"'{p}'" for p in OAUTH_PROVIDERS)


class OAuthCredential(Base, ProjectScopedMixin):
    __tablename__ = "oauth_credentials"
    __table_args__ = (
        Index("ix_oauth_credentials_project_provider", "project_id", "provider"),
        CheckConstraint(f"provider IN ({_PROVIDERS_SQL_LIST})", name="provider_allowed"),
    )

    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    account_email: Mapped[str] = mapped_column(String(255), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    encrypted_refresh_token: Mapped[str] = mapped_column(Text, nullable=False)

    connected_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    connected_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    # Free-form, provider-specific config resolved after connecting — e.g. which GA4 property
    # (a Google account can have access to several) this project's ingestion should read from.
    # Set via `PATCH /projects/{project_id}/oauth/google/config`.
    provider_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
