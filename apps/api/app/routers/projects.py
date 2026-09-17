from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import Principal
from app.deps import get_db, require_role
from app.schemas import ProjectConfig, ProjectCreate, ProjectOut, ProjectUpdate
from db.models.identity import Tenant
from db.models.project import Project

router = APIRouter(prefix="/projects", tags=["projects"])
log = structlog.get_logger("api.projects")


def _ensure_tenant_row(db: Session, principal: Principal) -> None:
    """First write for a tenant also materialises its `tenants` row (RLS WITH CHECK allows
    id == app.tenant_id)."""
    if db.get(Tenant, principal.tenant_id) is None:
        db.add(Tenant(id=principal.tenant_id, name="(unnamed)", slug=principal.tenant_id.hex[:12]))
        db.flush()


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)) -> list[Project]:
    return list(db.execute(select(Project).order_by(Project.created_at.desc())).scalars())


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(
    body: ProjectCreate,
    principal: Principal = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> Project:
    _ensure_tenant_row(db, principal)
    project = Project(
        tenant_id=principal.tenant_id,
        name=body.name,
        slug=body.slug,
        business_goal=body.business_goal,
        approval_mode="read_only",
    )
    db.add(project)
    try:
        db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "slug already in use") from exc
    return project


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: uuid.UUID, db: Session = Depends(get_db)) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    return project


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    principal: Principal = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> Project:
    """The operational kill switch (Phase 13 hardening): setting `approval_mode="read_only"` is
    the fastest way to stop a project from applying any new autonomous action —
    `execution.approval.resolve` returns `"blocked"` for every action class once it's set, checked
    before every write. Logged at `warning` since flipping this is a consequential, rare action."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")

    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no fields to update")
    for field, value in updates.items():
        setattr(project, field, value)
    log.warning("project.updated", project_id=str(project_id), tenant_id=str(principal.tenant_id),
               updated_by=str(principal.user_id), fields=updates)
    return project


@router.get("/{project_id}/config", response_model=ProjectConfig)
def get_config(project_id: uuid.UUID, db: Session = Depends(get_db)) -> ProjectConfig:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    return ProjectConfig(**project.config)


@router.put("/{project_id}/config", response_model=ProjectConfig)
def put_config(
    project_id: uuid.UUID,
    body: ProjectConfig,
    _: Principal = Depends(require_role("operator")),
    db: Session = Depends(get_db),
) -> ProjectConfig:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    project.config = body.model_dump()
    if body.business_goal:
        project.business_goal = body.business_goal
    db.add(project)
    return body
