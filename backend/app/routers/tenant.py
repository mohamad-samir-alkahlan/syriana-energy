from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.config import settings
from app.db import get_db
from app.deps import (Principal, current_principal, get_scoped, parse_uuid, require_feature, require_roles,
                      require_user_roles, user_only)
from app.errors import err
from app.models import Device, Membership, Tenant, User
from app.security import hash_password
from app.services import control
from app.services.tenants import (DOMAIN, HEX, create_tenant, device_count, family_device_count, tenant_out, valid_tz)

router = APIRouter(prefix="/api", tags=["tenant"])


class TenantPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    timezone: str | None = None


class BrandingPatch(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    name_ar: str | None = Field(default=None, max_length=100)
    logo_url: str | None = Field(default=None, max_length=500)
    primary_color: str | None = None
    accent_color: str | None = None
    support_email: EmailStr | None = None
    custom_domain: str | None = None


@router.get("/tenant")
async def get_tenant(p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    return await tenant_out(db, p.tenant)


@router.patch("/tenant")
async def patch_tenant(body: TenantPatch, p: Principal = Depends(require_roles("owner", "admin")),
                       db: AsyncSession = Depends(get_db, scope="function")):
    if body.name is not None:
        p.tenant.name = body.name.strip()
    if body.timezone is not None:
        if not valid_tz(body.timezone):
            raise err(422, "validation_error", "Unknown timezone")
        p.tenant.timezone = body.timezone
    return await tenant_out(db, p.tenant)


def _reserved_domain(dom: str) -> bool:
    from urllib.parse import urlsplit
    reserved = {h.strip().lower() for h in settings.reserved_domains.split(",") if h.strip()}
    if base := (urlsplit(settings.public_base_url).hostname or "").lower():
        reserved.add(base)
    return any(dom == r or dom.endswith("." + r) for r in reserved)


@router.patch("/tenant/branding")
async def patch_branding(body: BrandingPatch, p: Principal = Depends(require_roles("owner", "admin")),
                         db: AsyncSession = Depends(get_db, scope="function")):
    t = p.tenant
    if "white_label" not in p.plan.features:
        # an installer's own admin may brand a customer tenant even though the customer plan has no white_label
        via_parent = bool(t.parent_id and p.user and await db.get(Membership, (p.user.id, t.id)) is None)
        if not via_parent:
            raise err(403, "feature_not_in_plan", feature="white_label")
    data = body.model_dump(exclude_unset=True)
    brand = dict(t.branding or {})
    for k in ("name", "name_ar", "logo_url", "support_email"):
        if k in data:
            if data[k]:
                brand[k] = str(data[k])
            else:
                brand.pop(k, None)
    for k in ("primary_color", "accent_color"):
        if k in data:
            if data[k] and not HEX.match(data[k]):
                raise err(422, "validation_error", f"{k} must look like #RRGGBB")
            if data[k]:
                brand[k] = data[k]
            else:
                brand.pop(k, None)
    if "custom_domain" in data:
        dom = (data["custom_domain"] or "").strip().lower() or None
        if dom and not DOMAIN.match(dom):
            raise err(422, "validation_error", "custom_domain is not a valid hostname")
        if dom and _reserved_domain(dom):
            raise err(422, "validation_error", "custom_domain is reserved")
        t.custom_domain = dom
    t.branding = brand
    try:
        await db.flush()
    except IntegrityError:
        raise err(409, "conflict", "That domain is already in use")
    return await tenant_out(db, t)


@router.get("/tenant/usage")
async def usage(p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    return {"devices": await device_count(db, p.tenant.id), "max_devices": p.plan.max_devices,
            "history_days": p.plan.history_days}


# ---------------------------------------------------------------- customers (installer)
class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    owner_email: EmailStr
    owner_name: str = Field(min_length=1, max_length=200)
    password: str | None = Field(default=None, min_length=8, max_length=128)


def _installer_only(p: Principal) -> None:
    if p.tenant.type != "installer" or p.tenant.parent_id:
        raise err(403, "feature_not_in_plan", feature="customers")


async def _customer_item(db: AsyncSession, c: Tenant) -> dict:
    n = await device_count(db, c.id)
    online = (await db.execute(select(func.count(Device.id)).where(
        Device.tenant_id == c.id, Device.last_seen > clock.utcnow() - timedelta(minutes=3)))).scalar_one()
    return {"id": str(c.id), "name": c.name, "devices": n, "online": int(online), "plan": c.plan_code,
            "created_at": c.created_at.isoformat()}


@router.get("/customers")
async def list_customers(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                         p: Principal = Depends(require_feature("customers", ("owner", "admin"))),
                         db: AsyncSession = Depends(get_db, scope="function")):
    _installer_only(p)
    q = select(Tenant).where(Tenant.parent_id == p.tenant.id)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (await db.execute(q.order_by(Tenant.created_at.desc()).limit(limit).offset(offset))).scalars().all()
    return {"items": [await _customer_item(db, c) for c in rows], "total": total}


@router.post("/customers", status_code=201)
async def create_customer(body: CustomerIn, p: Principal = Depends(require_feature("customers", ("owner", "admin"))),
                          db: AsyncSession = Depends(get_db, scope="function")):
    _installer_only(p)
    email = body.owner_email.lower()
    if (await db.execute(select(User.id).where(User.email == email))).first():
        raise err(409, "email_taken")
    pw = body.password or secrets.token_urlsafe(9)
    child = await create_tenant(db, body.name.strip(), "home", p.tenant.id, p.tenant.plan_code, "ar", p.tenant.timezone)
    user = User(email=email, name=body.owner_name.strip(), password_hash=hash_password(pw), locale="ar")
    db.add(user)
    await db.flush()
    db.add(Membership(user_id=user.id, tenant_id=child.id, role="owner"))
    await control.audit(db, None, "customer.create", str(child.id), {"by": str(p.user.id) if p.user else None},
                        tenant_id=p.tenant.id)
    await db.flush()
    item = await _customer_item(db, child)
    if not body.password:
        item["initial_password"] = pw  # shown once; the installer hands it to the customer
    return item


@router.delete("/customers/{cid}", status_code=204)
async def delete_customer(cid: str, p: Principal = Depends(require_feature("customers", ("owner", "admin"))),
                          db: AsyncSession = Depends(get_db, scope="function")):
    _installer_only(p)
    user_only(p)  # deleting a customer with its users is too destructive for an API key
    child = await get_scoped(db, Tenant, cid, p.tenant.id, col="parent_id")
    member_ids = [r[0] for r in (await db.execute(select(Membership.user_id).where(Membership.tenant_id == child.id)))]
    for uid in member_ids:  # users that belong only to this customer go away with it
        others = (await db.execute(select(func.count()).select_from(Membership).where(
            Membership.user_id == uid, Membership.tenant_id != child.id))).scalar_one()
        u = await db.get(User, uid)
        if others == 0 and u is not None and not u.is_superadmin:
            await db.delete(u)
    await control.audit(db, None, "customer.delete", str(child.id), {"name": child.name}, tenant_id=p.tenant.id)
    await db.delete(child)
    await db.flush()


# ---------------------------------------------------------------- team
class UserIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    role: Literal["owner", "admin", "viewer"] = "viewer"
    password: str = Field(min_length=8, max_length=128)


class RolePatch(BaseModel):
    role: Literal["owner", "admin", "viewer"]


def _member_out(u: User, role: str) -> dict:
    return {"id": str(u.id), "email": u.email, "name": u.name, "role": role, "locale": u.locale,
            "totp_enabled": u.totp_enabled, "created_at": u.created_at.isoformat()}


async def _owner_count(db: AsyncSession, tenant_id) -> int:
    return (await db.execute(select(func.count()).select_from(Membership).where(
        Membership.tenant_id == tenant_id, Membership.role == "owner"))).scalar_one()


@router.get("/users")
async def list_users(p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    rows = (await db.execute(select(User, Membership.role).join(Membership, Membership.user_id == User.id)
                             .where(Membership.tenant_id == p.tenant.id).order_by(User.created_at))).all()
    return [_member_out(u, r) for u, r in rows]


@router.post("/users", status_code=201)
async def add_user(body: UserIn, p: Principal = Depends(require_user_roles("owner", "admin")), db: AsyncSession = Depends(get_db, scope="function")):
    if body.role == "owner" and p.role != "owner":
        raise err(403, "forbidden", "Only an owner can add another owner")
    email = body.email.lower()
    if (await db.execute(select(User.id).where(User.email == email))).first():
        raise err(409, "email_taken")
    u = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password), locale="ar")
    db.add(u)
    await db.flush()
    db.add(Membership(user_id=u.id, tenant_id=p.tenant.id, role=body.role))
    await control.audit(db, None, "user.add", email, {"role": body.role}, tenant_id=p.tenant.id)
    await db.flush()
    return _member_out(u, body.role)


async def _member(db: AsyncSession, tenant_id, uid: str) -> tuple[User, Membership]:
    m = await db.get(Membership, (parse_uuid(uid), tenant_id))
    u = await db.get(User, m.user_id) if m else None
    if m is None or u is None:
        raise err(404, "not_found")
    return u, m


@router.patch("/users/{uid}")
async def patch_user(uid: str, body: RolePatch, p: Principal = Depends(require_user_roles("owner", "admin")),
                     db: AsyncSession = Depends(get_db, scope="function")):
    u, m = await _member(db, p.tenant.id, uid)
    if (body.role == "owner" or m.role == "owner") and p.role != "owner":
        raise err(403, "forbidden", "Only an owner can change owner roles")
    if m.role == "owner" and body.role != "owner" and await _owner_count(db, p.tenant.id) <= 1:
        raise err(409, "last_owner")
    m.role = body.role
    await control.audit(db, None, "user.role", str(u.id), {"role": body.role}, tenant_id=p.tenant.id)
    return _member_out(u, m.role)


@router.delete("/users/{uid}", status_code=204)
async def delete_user(uid: str, p: Principal = Depends(require_user_roles("owner", "admin")), db: AsyncSession = Depends(get_db, scope="function")):
    u, m = await _member(db, p.tenant.id, uid)
    if p.user and u.id == p.user.id:
        raise err(400, "bad_request", "You cannot remove yourself")
    if m.role == "owner" and (p.role != "owner" or await _owner_count(db, p.tenant.id) <= 1):
        raise err(409, "last_owner") if p.role == "owner" else err(403, "forbidden")
    await db.delete(m)
    others = (await db.execute(select(func.count()).select_from(Membership).where(
        Membership.user_id == u.id, Membership.tenant_id != p.tenant.id))).scalar_one()
    if others == 0 and not u.is_superadmin:
        await db.delete(u)
    await control.audit(db, None, "user.remove", str(u.id), tenant_id=p.tenant.id)
