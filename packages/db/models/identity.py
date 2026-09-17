"""Tenants, users, memberships (A-TO-Z-PLAN.md §F core).

`users` is the one identity-global table (mirrors Supabase auth). Every other table is
tenant-scoped. `memberships` is the tenant<->user bridge and carries RLS."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, TenantMixin, TimestampMixin, UUIDPKMixin


class Tenant(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)

    # RLS keys on id (a tenant may read only its own row).
    tenant_rls_column = "id"


class User(Base, UUIDPKMixin, TimestampMixin):
    """Identity-global. No RLS — access is gated by membership joins."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    supabase_uid: Mapped[str | None] = mapped_column(String(64), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(200))


class Membership(Base, TenantMixin):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_user"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer")  # owner/admin/operator/viewer
    invited_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    last_active_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
