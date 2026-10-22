"""Public, assistant, API keys, billing (Odoo) and platform admin endpoints."""
from __future__ import annotations

import hmac
import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.cache import limiter
from app.config import VERSION, settings
from app.db import get_db
from app.deps import Principal, current_principal, get_scoped, parse_uuid, require_feature, require_superadmin
from app.errors import err
from app.models import ApiKey, BillingEvent, Device, Membership, Plan, Tenant, User
from app.plans import ALL_FEATURES
from app.security import generate_api_key
from app.services import assistant as ai
from app.services import control
from app.services.tenants import branding_for_host, effective_plan, plan_out

public = APIRouter(prefix="/api", tags=["public"])


@public.get("/health")
async def health():
    return {"ok": True, "version": VERSION}


@public.get("/public/branding")
async def branding(request: Request, host: str | None = None, db: AsyncSession = Depends(get_db, scope="function")):
    h = host or request.headers.get("x-forwarded-host") or request.headers.get("host")
    return await branding_for_host(db, h)


@public.get("/public/plans")
async def plans(db: AsyncSession = Depends(get_db, scope="function")):
    rows = (await db.execute(select(Plan).order_by(Plan.sort))).scalars().all()
    return [plan_out(p) for p in rows]


# ------------------------------------------------------------------ assistant
assistant = APIRouter(prefix="/api/assistant", tags=["assistant"])


class ChatMsg(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class ChatIn(BaseModel):
    messages: list[ChatMsg] = Field(min_length=1, max_length=40)
    device_id: str | None = None


# test hook: tests set this to an httpx.MockTransport
assistant_transport = None


@assistant.post("/chat")
async def chat(body: ChatIn, p: Principal = Depends(require_feature("ai")), db: AsyncSession = Depends(get_db, scope="function")):
    if body.messages[-1].role != "user":
        raise err(422, "validation_error", "The last message must be from the user")
    if not settings.anthropic_api_key:
        raise err(503, "ai_unavailable")
    if sum(len(m.content) for m in body.messages) > 40_000:
        raise err(422, "validation_error", "Conversation is too long; start a new one")
    tid = p.tenant.id
    if (await limiter.count(f"ai-h:{tid}") >= settings.assistant_hourly_limit
            or await limiter.count(f"ai-d:{tid}") >= settings.assistant_daily_limit):
        raise err(429, "rate_limited")
    await limiter.incr(f"ai-h:{tid}", 3600)
    await limiter.incr(f"ai-d:{tid}", 86400)
    if body.device_id:
        await get_scoped(db, Device, body.device_id, p.tenant.id)
    locale = p.user.locale if p.user else "ar"
    return await ai.chat(db, p.tenant.id, p.plan.history_days, locale, [m.model_dump() for m in body.messages],
                         body.device_id, transport=assistant_transport)


# ------------------------------------------------------------------ API keys
keys = APIRouter(prefix="/api/api-keys", tags=["api-keys"])


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


def _key_out(k: ApiKey) -> dict:
    return {"id": str(k.id), "name": k.name, "prefix": k.prefix, "created_at": k.created_at.isoformat(),
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None}


def _user_session_only(p: Principal) -> None:
    if p.via != "session":
        raise err(403, "forbidden", "API keys can only be managed from a signed-in session")


@keys.get("")
async def list_keys(p: Principal = Depends(require_feature("api", ("owner", "admin"))), db: AsyncSession = Depends(get_db, scope="function")):
    _user_session_only(p)
    rows = (await db.execute(select(ApiKey).where(ApiKey.tenant_id == p.tenant.id).order_by(ApiKey.created_at))).scalars()
    return [_key_out(k) for k in rows]


@keys.post("", status_code=201)
async def create_key(body: KeyIn, p: Principal = Depends(require_feature("api", ("owner", "admin"))), db: AsyncSession = Depends(get_db, scope="function")):
    _user_session_only(p)
    plain, prefix, h = generate_api_key()
    k = ApiKey(tenant_id=p.tenant.id, user_id=p.user.id if p.user else None, name=body.name.strip(), prefix=prefix, key_hash=h)
    db.add(k)
    await db.flush()
    await control.audit(db, None, "apikey.create", str(k.id), {"name": k.name}, tenant_id=p.tenant.id)
    return {"id": str(k.id), "name": k.name, "key": plain}


@keys.delete("/{kid}", status_code=204)
async def delete_key(kid: str, p: Principal = Depends(require_feature("api", ("owner", "admin"))), db: AsyncSession = Depends(get_db, scope="function")):
    _user_session_only(p)
    k = await get_scoped(db, ApiKey, kid, p.tenant.id)
    await control.audit(db, None, "apikey.delete", str(k.id), tenant_id=p.tenant.id)
    await db.delete(k)


# ------------------------------------------------------------------ billing (Odoo)
billing = APIRouter(prefix="/api/billing", tags=["billing"])


class OdooIn(BaseModel):
    tenant_id: str | None = None
    email: EmailStr | None = None
    plan_code: str
    expires_at: datetime | None = None
    invoice_ref: str | None = Field(default=None, max_length=200)


@billing.post("/odoo/webhook")
async def odoo_webhook(body: OdooIn, x_odoo_secret: str | None = Header(default=None), db: AsyncSession = Depends(get_db, scope="function")):
    expected = settings.odoo_webhook_secret
    if not expected:
        raise err(503, "billing_not_configured")
    if not x_odoo_secret or not hmac.compare_digest(x_odoo_secret.encode(), expected.encode()):
        raise err(401, "invalid_secret")
    if body.invoice_ref:
        dup = (await db.execute(select(BillingEvent).where(BillingEvent.invoice_ref == body.invoice_ref))).scalar_one_or_none()
        if dup is not None:
            return {"ok": True, "duplicate": True}
    plan = await db.get(Plan, body.plan_code)
    if plan is None:
        raise err(422, "unknown_plan")
    tenant: Tenant | None = None
    if body.tenant_id:
        tenant = await db.get(Tenant, parse_uuid(body.tenant_id))
    elif body.email:
        tenant = (await db.execute(
            select(Tenant).join(Membership, Membership.tenant_id == Tenant.id).join(User, User.id == Membership.user_id)
            .where(User.email == body.email.lower(), User.email_verified_at.is_not(None),  # no squatted e-mails
                   Membership.role == "owner", Tenant.parent_id.is_(None))
            .order_by(Tenant.created_at).limit(1))).scalar_one_or_none()
    else:
        raise err(422, "validation_error", "tenant_id or email is required")
    if tenant is None:
        raise err(404, "not_found")
    tenant.plan_code = plan.code
    await db.refresh(tenant, attribute_names=["plan"])
    tenant.plan_expires_at = body.expires_at
    if plan.code == "installer" and tenant.type != "installer":
        tenant.type = "installer"
    if body.invoice_ref:
        db.add(BillingEvent(invoice_ref=body.invoice_ref, tenant_id=tenant.id,
                            payload={"plan_code": plan.code, "expires_at": body.expires_at.isoformat() if body.expires_at else None}))
    await control.audit(db, None, "billing.odoo", str(tenant.id),
                        {"plan": plan.code, "expires_at": body.expires_at.isoformat() if body.expires_at else None,
                         "invoice_ref": body.invoice_ref}, tenant_id=tenant.id)
    try:
        await db.flush()
    except IntegrityError:  # concurrent duplicate invoice
        return {"ok": True, "duplicate": True}
    return {"ok": True, "tenant_id": str(tenant.id), "plan_code": plan.code,
            "plan_expires_at": tenant.plan_expires_at.isoformat() if tenant.plan_expires_at else None}


# ------------------------------------------------------------------ platform admin
admin = APIRouter(prefix="/api/admin", tags=["admin"])


@admin.get("/stats")
async def stats(p: Principal = Depends(require_superadmin), db: AsyncSession = Depends(get_db, scope="function")):
    now = clock.utcnow()
    n_t = (await db.execute(select(func.count(Tenant.id)))).scalar_one()
    n_u = (await db.execute(select(func.count(User.id)))).scalar_one()
    n_d = (await db.execute(select(func.count(Device.id)))).scalar_one()
    n_on = (await db.execute(select(func.count(Device.id)).where(Device.last_seen > now - timedelta(minutes=3)))).scalar_one()
    by_plan = {code: 0 for (code,) in (await db.execute(select(Plan.code)))}
    for code, n in (await db.execute(select(Tenant.plan_code, func.count()).group_by(Tenant.plan_code))):
        by_plan[code] = n
    day = func.date(Tenant.created_at)
    since = (now - timedelta(days=29)).date()
    rows = {r[0].isoformat(): r[1] for r in (await db.execute(
        select(day, func.count()).where(day >= since).group_by(day)))}
    signups = [[(since + timedelta(days=i)).isoformat(), rows.get((since + timedelta(days=i)).isoformat(), 0)] for i in range(30)]
    # MRR estimate: monthly list price; per-device plans multiply by the family's device count
    mrr = 0.0
    plans = {pl.code: pl for pl in (await db.execute(select(Plan))).scalars()}
    dev_by_tenant = {tid: n for tid, n in (await db.execute(select(Device.tenant_id, func.count()).group_by(Device.tenant_id)))}
    tenants = (await db.execute(select(Tenant).where(Tenant.parent_id.is_(None), Tenant.suspended.is_(False)))).scalars().all()
    kids: dict[uuid.UUID, list[uuid.UUID]] = {}
    for tid, pid in (await db.execute(select(Tenant.id, Tenant.parent_id).where(Tenant.parent_id.is_not(None)))):
        kids.setdefault(pid, []).append(tid)
    for t in tenants:
        pl = plans.get(t.plan_code)
        if not pl or not pl.price_month or (t.plan_expires_at and t.plan_expires_at < now):
            continue
        if pl.per_device:
            mrr += pl.price_month * (dev_by_tenant.get(t.id, 0) + sum(dev_by_tenant.get(k, 0) for k in kids.get(t.id, [])))
        else:
            mrr += pl.price_month
    return {"tenants": n_t, "users": n_u, "devices": n_d, "devices_online": n_on, "by_plan": by_plan,
            "signups_30d": signups, "mrr_estimate": round(mrr, 2)}


async def _admin_item(db: AsyncSession, t: Tenant) -> dict:
    devs = (await db.execute(select(func.count(Device.id)).where(Device.tenant_id == t.id))).scalar_one()
    users = (await db.execute(select(func.count()).select_from(Membership).where(Membership.tenant_id == t.id))).scalar_one()
    owner = (await db.execute(select(User.email).join(Membership, Membership.user_id == User.id).where(
        Membership.tenant_id == t.id, Membership.role == "owner").order_by(User.created_at).limit(1))).scalar_one_or_none()
    return {"id": str(t.id), "name": t.name, "type": t.type, "plan": t.plan_code, "devices": devs, "users": users,
            "created_at": t.created_at.isoformat(), "suspended": t.suspended, "owner_email": owner,
            "parent_id": str(t.parent_id) if t.parent_id else None,
            "plan_expires_at": t.plan_expires_at.isoformat() if t.plan_expires_at else None}


@admin.get("/tenants")
async def admin_tenants(q: str | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                        p: Principal = Depends(require_superadmin), db: AsyncSession = Depends(get_db, scope="function")):
    stmt = select(Tenant)
    if q:
        like = f"%{q.strip()}%"
        owner_ids = select(Membership.tenant_id).join(User, User.id == Membership.user_id).where(User.email.ilike(like))
        stmt = stmt.where(Tenant.name.ilike(like) | Tenant.id.in_(owner_ids))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(Tenant.created_at.desc()).limit(limit).offset(offset))).scalars().all()
    return {"items": [await _admin_item(db, t) for t in rows], "total": total}


class AdminTenantPatch(BaseModel):
    plan_code: str | None = None
    plan_expires_at: datetime | None = None
    suspended: bool | None = None
    type: Literal["home", "installer"] | None = None


@admin.patch("/tenants/{tid}")
async def admin_patch_tenant(tid: str, body: AdminTenantPatch, p: Principal = Depends(require_superadmin),
                             db: AsyncSession = Depends(get_db, scope="function")):
    t = await db.get(Tenant, parse_uuid(tid))
    if t is None:
        raise err(404, "not_found")
    fs = body.model_fields_set
    if "plan_code" in fs and body.plan_code is not None:
        if await db.get(Plan, body.plan_code) is None:
            raise err(422, "unknown_plan")
        t.plan_code = body.plan_code
        await db.refresh(t, attribute_names=["plan"])
        # the installer plan implies an installer tenant (customers endpoints check the tenant type), same as the Odoo webhook
        if body.plan_code == "installer" and t.type != "installer" and t.parent_id is None and "type" not in fs:
            t.type = "installer"
    if "plan_expires_at" in fs:
        t.plan_expires_at = body.plan_expires_at
    if "suspended" in fs and body.suspended is not None:
        t.suspended = body.suspended
    if "type" in fs and body.type is not None:
        t.type = body.type
    await control.audit(db, None, "admin.tenant_patch", str(t.id), body.model_dump(mode="json", exclude_unset=True),
                        tenant_id=t.id)
    await db.flush()
    return await _admin_item(db, t)


@admin.get("/plans")
async def admin_plans(p: Principal = Depends(require_superadmin), db: AsyncSession = Depends(get_db, scope="function")):
    return [plan_out(x) for x in (await db.execute(select(Plan).order_by(Plan.sort))).scalars()]


class PlanPatch(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    name_ar: str | None = Field(default=None, max_length=100)
    price_month: float | None = Field(default=None, ge=0)
    price_year: float | None = Field(default=None, ge=0)
    max_devices: int | None = Field(default=None, ge=1, le=100000)
    history_days: int | None = Field(default=None, ge=1, le=3650)
    features: list[str] | None = None
    per_device: bool | None = None


@admin.patch("/plans/{code}")
async def admin_patch_plan(code: str, body: PlanPatch, p: Principal = Depends(require_superadmin), db: AsyncSession = Depends(get_db, scope="function")):
    plan = await db.get(Plan, code)
    if plan is None:
        raise err(404, "not_found")
    data = body.model_dump(exclude_unset=True)
    if "features" in data:
        bad = set(data["features"] or []) - set(ALL_FEATURES)
        if bad:
            raise err(422, "validation_error", f"Unknown features: {sorted(bad)}")
        data["features"] = list(dict.fromkeys(data["features"] or []))
    for k, v in data.items():
        if k in ("name", "name_ar", "max_devices", "history_days", "features", "per_device") and v is None:
            continue
        setattr(plan, k, v)
    await control.audit(db, None, "admin.plan_patch", code, data)
    await db.flush()
    return plan_out(plan)
