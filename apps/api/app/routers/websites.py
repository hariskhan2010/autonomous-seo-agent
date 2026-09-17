from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import Principal
from app.deps import get_db, require_role
from app.schemas import WebsiteCreate, WebsiteOut
from db.models.project import Project, Website

router = APIRouter(prefix="/websites", tags=["websites"])


@router.get("", response_model=list[WebsiteOut])
def list_websites(
    project_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[Website]:
    stmt = select(Website).order_by(Website.created_at.desc())
    if project_id is not None:
        stmt = stmt.where(Website.project_id == project_id)
    return list(db.execute(stmt).scalars())


@router.post("", response_model=WebsiteOut, status_code=status.HTTP_201_CREATED)
def create_website(
    body: WebsiteCreate,
    _: Principal = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> Website:
    project = db.get(Project, body.project_id)  # RLS scopes to tenant
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    website = Website(
        tenant_id=project.tenant_id,
        project_id=project.id,
        origin=str(body.origin).rstrip("/"),
        cms_type=body.cms_type,
    )
    db.add(website)
    try:
        db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "origin already registered") from exc
    return website


@router.get("/{website_id}", response_model=WebsiteOut)
def get_website(website_id: uuid.UUID, db: Session = Depends(get_db)) -> Website:
    website = db.get(Website, website_id)
    if website is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "website not found")
    return website
