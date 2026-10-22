"""Alert rule engine: evaluates rules on each reading (edge/level triggers with cooldown)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import i18n
from app.models import Alert, AlertRule, AlertState, Device, Tenant
from app.services import devices as dv
from app.services import notify
from app.services import readings as rd
from app.services.tenants import EffectivePlan, owner_locale

log = logging.getLogger(__name__)


async def _state(db: AsyncSession, rule: AlertRule, device: Device) -> AlertState:
    st = await db.get(AlertState, (rule.id, device.id))
    if st is None:
        st = AlertState(rule_id=rule.id, device_id=device.id, active=False, data={})
        db.add(st)
        await db.flush()
    return st


def _cooldown_ok(st: AlertState, rule: AlertRule, now: datetime) -> bool:
    return st.last_fired_at is None or now - st.last_fired_at >= timedelta(minutes=rule.cooldown_minutes or 0)


def _level(st: AlertState, rule: AlertRule, cond: bool, clear: bool, now: datetime) -> bool:
    """Level trigger with hysteresis: fires once when the condition becomes true and cooldown allows."""
    if cond and not st.active and _cooldown_ok(st, rule, now):
        st.active = True
        st.last_fired_at = now
        return True
    if st.active and clear:
        st.active = False
    return False


async def emit(db: AsyncSession, tenant: Tenant, plan: EffectivePlan, device: Device | None, kind: str,
               ctx: dict[str, Any], channels: list[str], now: datetime, severity: str | None = None) -> dict[str, Any]:
    msg = i18n.alert_message(kind, {"device": device.name if device else "", **ctx})
    sev = severity or i18n.SEVERITY.get(kind, "info")
    out = {"type": kind, "severity": sev, **msg, "device": {"id": str(device.id), "name": device.name} if device else None,
           "device_name": device.name if device else None, "tenant_id": str(tenant.id), "created_at": now.isoformat()}
    if "inapp" in channels:
        a = Alert(tenant_id=tenant.id, device_id=device.id if device else None, device_name=device.name if device else None,
                  type=kind, severity=sev, title=msg["title"], title_ar=msg["title_ar"], body=msg["body"],
                  body_ar=msg["body_ar"], read=False, created_at=now)
        db.add(a)
        await db.flush()
        out["id"] = str(a.id)
    lang = await owner_locale(db, tenant.id)
    try:
        out["sent"] = await notify.dispatch(tenant, plan.features, out, channels, lang)
    except Exception:  # noqa: BLE001
        log.exception("notification dispatch failed")
    return out


async def _outage_minutes(db: AsyncSession, device: Device, now: datetime) -> float | None:
    q = text("""
        SELECT min(ts) FROM readings WHERE device_id=:d AND ts < :now AND ts > COALESCE(
          (SELECT max(ts) FROM readings WHERE device_id=:d AND ts < :now AND metrics->>'grid_available'='true'),
          '-infinity'::timestamptz)""")
    start = (await db.execute(q, {"d": device.id, "now": now})).scalar()
    return (now - start).total_seconds() / 60 if start else None


async def process_reading(db: AsyncSession, device: Device, tenant: Tenant, plan: EffectivePlan,
                          metrics: dict[str, Any], prev: dict[str, Any] | None, now: datetime) -> list[dict[str, Any]]:
    rules = list((await db.execute(select(AlertRule).where(AlertRule.tenant_id == tenant.id,
                                                            AlertRule.enabled.is_(True)))).scalars())
    fired: list[dict[str, Any]] = []
    soc = metrics.get("battery_soc")
    for rule in rules:
        p = rule.params or {}
        t = rule.type
        ctx: dict[str, Any] | None = None
        if t == "battery_low" and soc is not None:
            thr = float(p.get("threshold_soc", 30))
            st = await _state(db, rule, device)
            if _level(st, rule, soc <= thr, soc >= min(100.0, thr + 5), now):
                ctx = {"soc": soc, "threshold": thr}
        elif t == "battery_full" and soc is not None:
            thr = float(p.get("threshold_soc", 100))
            st = await _state(db, rule, device)
            if _level(st, rule, soc >= thr, soc <= thr - 5, now):
                ctx = {"soc": soc}
        elif t in ("grid_lost", "grid_restored"):
            ga, pga = metrics.get("grid_available"), (prev or {}).get("grid_available")
            edge = (t == "grid_lost" and pga is True and ga is False) or (t == "grid_restored" and pga is False and ga is True)
            if edge:
                st = await _state(db, rule, device)
                if _cooldown_ok(st, rule, now):
                    st.last_fired_at = now
                    ctx = {"soc": soc}
                    if t == "grid_restored":
                        ctx["outage_minutes"] = await _outage_minutes(db, device, now)
        elif t == "overload":
            pct = metrics.get("load_percent")
            thr, minutes = float(p.get("threshold_percent", 90)), float(p.get("minutes", 3))
            st = await _state(db, rule, device)
            if pct is not None and pct >= thr:
                st.since = st.since or now
                held = (now - st.since).total_seconds() / 60
                if held >= minutes and _level(st, rule, True, False, now):
                    ctx = {"percent": pct, "threshold": thr, "minutes": round(held, 1)}
            else:
                st.since, st.active = None, False
        elif t == "fault":
            codes = metrics.get("fault_codes") or []
            cond = metrics.get("mode") == "fault" or bool(codes)
            st = await _state(db, rule, device)
            if _level(st, rule, cond, not cond, now):
                ctx = {"codes": codes, "mode": metrics.get("mode")}
        elif t == "high_temperature":
            temp = metrics.get("inverter_temperature")
            thr = float(p.get("threshold_c", 60))
            if temp is not None:
                st = await _state(db, rule, device)
                if _level(st, rule, temp >= thr, temp <= thr - 5, now):
                    ctx = {"temp": temp, "threshold": thr}
        elif t == "device_offline":
            st = await _state(db, rule, device)  # data is flowing => re-arm
            st.active = False
        if ctx is not None:
            fired.append(await emit(db, tenant, plan, device, t, ctx, rule.channels or [], now))
    return fired


async def check_offline(db: AsyncSession, now: datetime) -> list[dict[str, Any]]:
    """Level-triggered device_offline for every device whose data stopped (called by the worker)."""
    from app.services.tenants import effective_plan
    rows = (await db.execute(select(AlertRule, Tenant).join(Tenant, Tenant.id == AlertRule.tenant_id)
                             .where(AlertRule.type == "device_offline", AlertRule.enabled.is_(True)))).all()
    fired = []
    for rule, tenant in rows:
        minutes = float((rule.params or {}).get("minutes", 10))
        devices = list((await db.execute(select(Device).where(Device.tenant_id == tenant.id))).scalars())
        plan = None
        for d in devices:
            ref = d.last_seen or d.created_at
            age_min = (now - ref).total_seconds() / 60
            st = await _state(db, rule, d)
            if _level(st, rule, age_min >= minutes, age_min < minutes, now):
                plan = plan or await effective_plan(db, tenant)
                fired.append(await emit(db, tenant, plan, d, "device_offline", {"minutes": age_min}, rule.channels or [], now))
    return fired


async def check_daily_summary(db: AsyncSession, now: datetime) -> list[dict[str, Any]]:
    from app.services.tenants import effective_plan
    rows = (await db.execute(select(AlertRule, Tenant).join(Tenant, Tenant.id == AlertRule.tenant_id)
                             .where(AlertRule.type == "daily_summary", AlertRule.enabled.is_(True)))).all()
    fired = []
    for rule, tenant in rows:
        local = now.astimezone(ZoneInfo(tenant.timezone))
        if local.hour < int((rule.params or {}).get("hour_local", 21)):
            continue
        today = local.date().isoformat()
        devices = list((await db.execute(select(Device).where(Device.tenant_id == tenant.id))).scalars())
        plan = None
        for d in devices:
            st = await _state(db, rule, d)
            if st.data.get("date") == today:
                continue
            st.data = {"date": today}
            st.last_fired_at = now
            summ = await rd.today_summary(db, d, tenant.timezone)
            out_min = 0.0
            for o in summ["grid_outages"]:
                a = datetime.fromisoformat(o["from"])
                b = datetime.fromisoformat(o["to"]) if o["to"] else now
                out_min += (b - a).total_seconds() / 60
            plan = plan or await effective_plan(db, tenant)
            fired.append(await emit(db, tenant, plan, d, "daily_summary",
                                    {"pv": summ["pv_kwh"], "load": summ["load_kwh"], "grid": summ["grid_kwh"],
                                     "outages": len(summ["grid_outages"]), "outage_minutes": out_min},
                                    rule.channels or [], now))
    return fired
