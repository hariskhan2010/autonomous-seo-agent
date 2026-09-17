"""Request dependencies: principal, tenant-scoped DB session, RBAC (A-TO-Z-PLAN.md §Phase 1)."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Principal, principal_from_request
from db.models.identity import Membership
from db.session import tenant_session

# Role hierarchy: a higher role satisfies a lower requirement.
_RANK = {"viewer": 0, "operator": 1, "admin": 2, "owner": 3}


def get_principal(request: Request) -> Principal:
    return principal_from_request(request)


def get_db(principal: Principal = Depends(get_principal)) -> Iterator[Session]:
    with tenant_session(principal.tenant_id) as session:
        yield session


def _effective_roles(principal: Principal, db: Session) -> set[str]:
    if principal.roles:
        return set(principal.roles)
    row = db.execute(
        select(Membership.role).where(Membership.user_id == principal.user_id)
    ).scalar_one_or_none()
    return {row} if row else set()


def require_role(minimum: str) -> Callable[..., Principal]:
    want = _RANK[minimum]

    def _dep(
        principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
    ) -> Principal:
        roles = _effective_roles(principal, db)
        if not any(_RANK.get(r, -1) >= want for r in roles):
            have = sorted(roles) or "none"
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"requires role >= {minimum}; have {have}"
            )
        return principal

    return _dep


def require_project(request: Request, db: Session = Depends(get_db)) -> uuid.UUID:
    """Validate a `project_id` path param belongs to the caller's tenant (ABAC)."""
    from db.models.project import Project

    raw = request.path_params.get("project_id")
    try:
        pid = uuid.UUID(str(raw))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid project_id") from exc
    if db.get(Project, pid) is None:  # RLS already scopes this to the tenant
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    return pid
