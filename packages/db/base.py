"""SQLAlchemy declarative base + shared mixins (A-TO-Z-PLAN.md §F, DATABASE.md).

Every table carries `id`, `tenant_id`, `created_at`. Project-scoped tables add `project_id`
via `ProjectScopedMixin`. RLS policies are emitted by migrations using `db.rls`."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Stable constraint/index names so migrations diff cleanly.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPKMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )


class TimestampMixin:
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TenantMixin(UUIDPKMixin, TimestampMixin):
    """Tenant-scoped table: RLS keys on `tenant_id`."""

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)


class ProjectScopedMixin(TenantMixin):
    """Also project-scoped: RLS may additionally key on `project_id`."""

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
