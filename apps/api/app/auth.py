"""Authentication (A-TO-Z-PLAN.md §Phase 1, ADR-0004 = Supabase Auth).

The API only *verifies* a JWT and maps its claims to a `Principal`. Identity lives in Supabase;
tenant/project membership lives in our Postgres.

Two accepted token sources:
- Supabase-issued JWT (HS256, verified against `SUPABASE_JWT_SECRET`).
- Locally-issued JWT (HS256, `JWT_SECRET`) — for service tokens and tests.

Dev convenience: when `ENV=dev` and no `Authorization` header is present, the `X-Dev-User` /
`X-Dev-Tenant` headers synthesize a Principal so the stack runs without Supabase. Never active
outside dev."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import jwt
from fastapi import HTTPException, Request, status

from common.settings import settings


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    email: str | None = None
    roles: frozenset[str] = frozenset()

    def has_role(self, *allowed: str) -> bool:
        return bool(self.roles.intersection(allowed))


def _decode(token: str) -> dict[str, object]:
    errors: list[str] = []
    for secret in (settings.supabase_jwt_secret, settings.jwt_secret):
        if not secret:
            continue
        try:
            claims: dict[str, object] = jwt.decode(
                token,
                secret,
                algorithms=["HS256"],
                # exp is required: a token minted without one would otherwise never expire.
                options={"verify_aud": False, "require": ["exp", "sub"]},
            )
        except jwt.PyJWTError as exc:  # noqa: PERF203
            errors.append(str(exc))
            continue
        # Other JWTs signed with JWT_SECRET (the Google OAuth `state`, integrations/oauth/google.py)
        # carry a `purpose` claim — they are not API credentials, whatever else they contain.
        if "purpose" in claims:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token: not an API token")
        return claims
    detail = "; ".join(errors) or "no verification key configured"
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {detail}")


def principal_from_request(request: Request) -> Principal:
    header = request.headers.get("authorization", "")

    if not header and settings.env == "dev":
        dev_user = request.headers.get("x-dev-user")
        dev_tenant = request.headers.get("x-dev-tenant")
        if dev_user and dev_tenant:
            try:
                user_id, tenant_id = uuid.UUID(dev_user), uuid.UUID(dev_tenant)
            except ValueError as exc:  # a 400, not an unhandled 500
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, "X-Dev-User / X-Dev-Tenant must be UUIDs"
                ) from exc
            return Principal(
                user_id=user_id,
                tenant_id=tenant_id,
                email="dev@localhost",
                roles=frozenset({request.headers.get("x-dev-role", "owner")}),
            )

    if not header.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")

    claims = _decode(header.split(" ", 1)[1])
    try:
        user_id = uuid.UUID(str(claims.get("sub")))
        tenant_id = uuid.UUID(str(claims["tenant_id"]))
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "token missing sub/tenant_id"
        ) from exc

    raw_roles = claims.get("roles") or ([claims["role"]] if claims.get("role") else [])
    roles = [str(r) for r in raw_roles] if isinstance(raw_roles, list) else []
    email = claims.get("email")
    return Principal(
        user_id=user_id,
        tenant_id=tenant_id,
        email=str(email) if email else None,
        roles=frozenset(roles),
    )
