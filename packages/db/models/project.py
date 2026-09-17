"""Projects, websites, pages, urls (A-TO-Z-PLAN.md §F core / crawl).

`projects/{id}/config` (business goal, brand voice, CMS type, competitors, target markets) seeds
project memory (Plan.md §33) and lives in `Project.config` jsonb until Phase 9 formalises memory."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, ProjectScopedMixin, TenantMixin


class Project(Base, TenantMixin):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_projects_tenant_slug"),
        Index("ix_projects_tenant_slug", "tenant_id", "slug"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    business_goal: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    approval_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="read_only")


class Website(Base, ProjectScopedMixin):
    __tablename__ = "websites"
    __table_args__ = (
        UniqueConstraint("project_id", "origin", name="uq_websites_project_origin"),
        Index("ix_websites_tenant_project", "tenant_id", "project_id"),
    )

    origin: Mapped[str] = mapped_column(String(255), nullable=False)  # https://example.com
    cms_type: Mapped[str | None] = mapped_column(String(40))
    verified: Mapped[bool] = mapped_column(default=False, nullable=False)
    props: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")


class Url(Base, ProjectScopedMixin):
    """Normalized URL registry — the stable identity a Page attaches crawl history to."""

    __tablename__ = "urls"
    __table_args__ = (
        UniqueConstraint("project_id", "url_hash", name="uq_urls_project_hash"),
        Index("ix_urls_tenant_project", "tenant_id", "project_id"),
    )

    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # sha256 of normalized url
    first_seen_run: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class Page(Base, ProjectScopedMixin):
    """Latest known state of a URL. Crawl history/snapshots land in Phase 2."""

    __tablename__ = "pages"
    __table_args__ = (
        UniqueConstraint("project_id", "url_id", name="uq_pages_project_url"),
        Index("ix_pages_tenant_project", "tenant_id", "project_id"),
    )

    url_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("urls.id", ondelete="CASCADE"), nullable=False, index=True
    )
    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status_code: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(Text)
    content_fingerprint: Mapped[str | None] = mapped_column(String(64))  # simhash
    last_crawled_run: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    props: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
