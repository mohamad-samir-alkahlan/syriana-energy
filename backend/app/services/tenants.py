"""Tenant helpers: effective plan, branding, creation (default site + alert rules), usage."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.errors import err
from app.models import AlertRule, Device, Membership, Plan, Site, Tenant, User

DEFAULT_BRANDING = {
    "name": "Syriana Energy", "name_ar": "سيريانا للطاقة", "logo_url": None, "primary_color": "#DA7756",
    "accent_color": "#4F9D69", "support_email": "support@syriana.energy", "powered_by": True,
}
BRANDING_FIELDS = ["name", "name_ar", "logo_url", "primary_color", "accent_color", "support_email"]
CHILD_EXCLUDED_FEATURES = {"customers", "white_label"}

DEFAULT_RULES: list[dict[str, Any]] = [
    dict(type="battery_low", params={"threshold_soc": 30}, cooldown_minutes=60),
    dict(type="grid_lost", params={}, cooldown_minutes=5),
    dict(type="grid_restored", params={}, cooldown_minutes=5),
    dict(type="overload", params={"threshold_percent": 90, "minutes": 3}, cooldown_minutes=15),
    dict(type="fault", params={}, cooldown_minutes=30),
    dict(type="device_offline", params={"minutes": 10}, cooldown_minutes=60),
    dict(type="daily_summary", params={"hour_local": 21}, cooldown_minutes=0),
]
RULE_TYPES = {"battery_low", "battery_full", "grid_lost", "grid_restored", "overload", "fault", "device_offline",
              "high_temperature", "daily_summary"}
RULE_PARAM_DEFAULTS = {
    "battery_low": {"threshold_soc": 30}, "battery_full": {"threshold_soc": 100}, "grid_lost": {}, "grid_restored": {},
    "overload": {"threshold_percent": 90, "minutes": 3}, "fault": {}, "device_offline": {"minutes": 10},
    "high_temperature": {"threshold_c": 60}, "daily_summary": {"hour_local": 21},
}
DEFAULT_COOLDOWN = {"battery_low": 60, "battery_full": 120, "grid_lost": 5, "grid_restored": 5, "overload": 15,
                    "fault": 30, "device_offline": 60, "high_temperature": 30, "daily_summary": 0}


@dataclass
class EffectivePlan:
    plan: Plan
    max_devices: int
    history_days: int
    features: set[str] = field(default_factory=set)
    inherited: bool = False

    @property
    def code(self) -> str:
        return self.plan.code

    def has(self, feature: str) -> bool:
        return feature in self.features


async def get_plan(db: AsyncSession, code: str) -> Plan:
    p = await db.get(Plan, code)
    if p is None:
        raise err(500, "unknown_plan", f"plan {code} missing; run `python -m app.cli seed-plans`")
    return p


async def effective_plan(db: AsyncSession, tenant: Tenant) -> EffectivePlan:
    src = tenant
    inherited = False
    if tenant.parent_id:
        parent = await db.get(Tenant, tenant.parent_id)
        if parent is not None:
            src, inherited = parent, True
    plan = src.plan
    if src.plan_code != "free" and src.plan_expires_at and src.plan_expires_at < clock.utcnow():
        plan = await get_plan(db, "free")
    feats = set(plan.features or [])
    if inherited:
        feats -= CHILD_EXCLUDED_FEATURES
    return EffectivePlan(plan, plan.max_devices, plan.history_days, feats, inherited)


def plan_out(p: Plan, features: set[str] | None = None) -> dict[str, Any]:
    feats = list(p.features or [])
    if features is not None:  # effective features (child tenants never get customers/white_label)
        feats = [f for f in feats if f in features]
    return {"code": p.code, "name": p.name, "name_ar": p.name_ar, "price_month": p.price_month,
            "price_year": p.price_year, "currency": p.currency, "max_devices": p.max_devices,
            "history_days": p.history_days, "features": feats, "per_device": p.per_device}


def _clean_brand(b: dict[str, Any] | None) -> dict[str, Any]:
    return {k: v for k, v in (b or {}).items() if k in BRANDING_FIELDS and v}


async def resolve_branding(db: AsyncSession, tenant: Tenant) -> dict[str, Any]:
    chain = [tenant]
    if tenant.parent_id:
        parent = await db.get(Tenant, tenant.parent_id)
        if parent is not None:
            chain.append(parent)
    out = dict(DEFAULT_BRANDING)
    custom_src: Tenant | None = None
    for t in chain:  # own branding wins; otherwise inherit the parent's
        b = _clean_brand(t.branding)
        if b:
            out.update(b)
            custom_src = t
            break
    out["powered_by"] = True
    if custom_src is not None:
        ep = await effective_plan(db, custom_src)  # the branding owner's own plan
        out["powered_by"] = "white_label" not in ep.features
    return out


async def branding_for_host(db: AsyncSession, host: str | None) -> dict[str, Any]:
    if host:
        h = host.strip().lower().split(":")[0]
        t = (await db.execute(select(Tenant).where(Tenant.custom_domain == h))).scalar_one_or_none()
        if t is not None:
            return await resolve_branding(db, t)
    return dict(DEFAULT_BRANDING)


async def tenant_out(db: AsyncSession, t: Tenant) -> dict[str, Any]:
    ep = await effective_plan(db, t)
    return {"id": str(t.id), "name": t.name, "type": t.type, "parent_id": str(t.parent_id) if t.parent_id else None,
            "plan": plan_out(ep.plan, ep.features), "plan_expires_at": t.plan_expires_at.isoformat() if t.plan_expires_at else None,
            "branding": await resolve_branding(db, t), "custom_domain": t.custom_domain, "timezone": t.timezone,
            "created_at": t.created_at.isoformat() if t.created_at else None}


def valid_tz(tz: str) -> bool:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        ZoneInfo(tz)
        return True
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return False


async def create_tenant(db: AsyncSession, name: str, type_: str = "home", parent_id: uuid.UUID | None = None,
                        plan_code: str = "free", locale: str = "ar", timezone: str = "Asia/Damascus") -> Tenant:
    t = Tenant(name=name, type=type_, parent_id=parent_id, plan_code=plan_code, timezone=timezone, branding={},
               telegram_chats=[], email_channel={"enabled": False, "address": None},
               webhook_channel={"enabled": False, "url": None})
    db.add(t)
    await db.flush()
    await db.refresh(t, attribute_names=["plan"])
    db.add(Site(tenant_id=t.id, name="المنزل" if locale == "ar" else "Home", timezone=timezone))
    for r in DEFAULT_RULES:
        db.add(AlertRule(tenant_id=t.id, type=r["type"], enabled=True, params=r["params"],
                         channels=["inapp", "telegram"], cooldown_minutes=r["cooldown_minutes"]))
    await db.flush()
    return t


def family_root(t: Tenant) -> uuid.UUID:
    return t.parent_id or t.id


async def family_device_count(db: AsyncSession, t: Tenant) -> int:
    root = family_root(t)
    q = select(func.count(Device.id)).where(
        Device.tenant_id.in_(select(Tenant.id).where(or_(Tenant.id == root, Tenant.parent_id == root))))
    return int((await db.execute(q)).scalar_one())


async def device_count(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    return int((await db.execute(select(func.count(Device.id)).where(Device.tenant_id == tenant_id))).scalar_one())


async def owner_locale(db: AsyncSession, tenant_id: uuid.UUID) -> str:
    q = (select(User.locale).join(Membership, Membership.user_id == User.id)
         .where(Membership.tenant_id == tenant_id, Membership.role == "owner").order_by(User.created_at).limit(1))
    r = (await db.execute(q)).scalar_one_or_none()
    return r or "ar"


HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
DOMAIN = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")
