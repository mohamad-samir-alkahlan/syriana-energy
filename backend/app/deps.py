"""Authentication, tenant scoping, roles and plan-feature enforcement."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.db import get_db
from app.errors import err
from app.models import ApiKey, AuthSession, Membership, Tenant, User
from app.security import API_KEY_PREFIX, decode_jwt, hash_api_key
from app.services.tenants import EffectivePlan, effective_plan

COOKIE = "se_session"


@dataclass
class Principal:
    tenant: Tenant
    role: str
    plan: EffectivePlan
    user: User | None = None
    via: str = "session"  # session | api_key
    session_id: str | None = None
    api_key_id: uuid.UUID | None = None
    api_key_name: str | None = None

    @property
    def is_superadmin(self) -> bool:
        return bool(self.user and self.user.is_superadmin)

    @property
    def actor_name(self) -> str:
        return self.user.name if self.user else f"API key: {self.api_key_name or '?'}"


async def role_in_tenant(db: AsyncSession, user: User, tenant: Tenant) -> str | None:
    m = await db.get(Membership, (user.id, tenant.id))
    if m:
        return m.role
    if tenant.parent_id:  # installer owners/admins act inside their customers' tenants
        pm = await db.get(Membership, (user.id, tenant.parent_id))
        if pm and pm.role in ("owner", "admin"):
            return "admin"
    if user.is_superadmin:
        return "owner"
    return None


async def principal_from_api_key(db: AsyncSession, token: str) -> Principal:
    key = (await db.execute(select(ApiKey).where(ApiKey.key_hash == hash_api_key(token)))).scalar_one_or_none()
    if key is None:
        raise err(401, "unauthorized")
    tenant = await db.get(Tenant, key.tenant_id)
    if tenant is None:
        raise err(401, "unauthorized")
    if tenant.suspended:
        raise err(403, "tenant_suspended")
    plan = await effective_plan(db, tenant)
    if "api" not in plan.features:
        raise err(403, "feature_not_in_plan", feature="api")
    key.last_used_at = clock.utcnow()
    return Principal(tenant=tenant, role="admin", plan=plan, user=None, via="api_key", api_key_id=key.id, api_key_name=key.name)


async def current_principal(request: Request, db: AsyncSession = Depends(get_db, scope="function")) -> Principal:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token.startswith(API_KEY_PREFIX):
            return await principal_from_api_key(db, token)
        raise err(401, "unauthorized")
    cookie = request.cookies.get(COOKIE)
    if not cookie:
        raise err(401, "unauthorized")
    claims = decode_jwt(cookie)
    if not claims:
        raise err(401, "unauthorized")
    sess = await db.get(AuthSession, claims["jti"])
    if sess is None or sess.expires_at < clock.utcnow() or str(sess.user_id) != claims["sub"]:
        raise err(401, "unauthorized")
    user = await db.get(User, sess.user_id)
    tenant = await db.get(Tenant, sess.tenant_id)
    if user is None or tenant is None:
        raise err(401, "unauthorized")
    role = await role_in_tenant(db, user, tenant)
    if role is None:
        raise err(401, "unauthorized")
    if tenant.suspended and not user.is_superadmin:
        raise err(403, "tenant_suspended")
    plan = await effective_plan(db, tenant)
    return Principal(tenant=tenant, role=role, plan=plan, user=user, via="session", session_id=sess.jti)


def require_roles(*roles: str) -> Callable[..., Awaitable[Principal]]:
    async def dep(p: Principal = Depends(current_principal)) -> Principal:
        if p.role not in roles:
            raise err(403, "forbidden")
        return p
    return dep


def require_feature(feature: str, roles: tuple[str, ...] | None = None) -> Callable[..., Awaitable[Principal]]:
    async def dep(p: Principal = Depends(current_principal)) -> Principal:
        if roles and p.role not in roles:
            raise err(403, "forbidden")
        if feature not in p.plan.features:
            raise err(403, "feature_not_in_plan", feature=feature)
        return p
    return dep


async def require_superadmin(p: Principal = Depends(current_principal)) -> Principal:
    if not p.is_superadmin:
        raise err(403, "forbidden")
    return p


def user_only(p: Principal = Depends(current_principal)) -> Principal:
    if p.user is None:
        raise err(403, "forbidden", "This endpoint requires a signed-in user")
    return p


def require_user_roles(*roles: str) -> Callable[..., Awaitable[Principal]]:
    """Like require_roles, but refuses API keys (account management needs a signed-in user)."""
    async def dep(p: Principal = Depends(require_roles(*roles))) -> Principal:
        return user_only(p)
    return dep


def parse_uuid(v: str | uuid.UUID) -> uuid.UUID:
    if isinstance(v, uuid.UUID):
        return v
    try:
        return uuid.UUID(str(v))
    except (ValueError, AttributeError):
        raise err(404, "not_found")


async def get_scoped(db: AsyncSession, model: Any, id_: str | uuid.UUID, tenant_id: uuid.UUID, col: str = "tenant_id"):
    """Fetch a row by id restricted to the caller's tenant; cross-tenant access is a 404."""
    uid = parse_uuid(id_)
    row = (await db.execute(select(model).where(model.id == uid, getattr(model, col) == tenant_id))).scalar_one_or_none()
    if row is None:
        raise err(404, "not_found")
    return row
