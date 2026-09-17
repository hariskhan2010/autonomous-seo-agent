"""Request/response models (A-TO-Z-PLAN.md §24 — OpenAPI is the contract)."""

from __future__ import annotations

import datetime
import uuid

from pydantic import BaseModel, Field, HttpUrl


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")
    business_goal: str | None = None


class ProjectUpdate(BaseModel):
    """Deliberately narrow: the operational kill switch, not a general project editor.
    `name`/`slug` are not editable here — changing those is a bigger decision than a PATCH should
    make casually; project memory goes through `PUT /projects/{id}/config` instead."""

    approval_mode: str | None = Field(default=None, pattern=r"^(read_only|assisted|autonomous)$")


class ProjectConfig(BaseModel):
    """Seeds project memory (Plan.md §33)."""

    business_goal: str | None = None
    brand_voice: str | None = None
    cms_type: str | None = None
    competitors: list[str] = []
    target_markets: list[str] = []
    extra: dict[str, object] = {}


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    business_goal: str | None
    approval_mode: str
    config: dict[str, object]
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class WebsiteCreate(BaseModel):
    project_id: uuid.UUID
    origin: HttpUrl
    cms_type: str | None = None


class WebsiteOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    origin: str
    cms_type: str | None
    verified: bool
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class Page(BaseModel):
    data: list[object]
    next_cursor: str | None = None


class OAuthStartOut(BaseModel):
    authorization_url: str


class OAuthStatusOut(BaseModel):
    connected: bool
    account_email: str | None = None
    connected_at: datetime.datetime | None = None
    revoked_at: datetime.datetime | None = None


class OAuthConfigUpdate(BaseModel):
    ga4_property_id: str | None = Field(default=None, max_length=80)
