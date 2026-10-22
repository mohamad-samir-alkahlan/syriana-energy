"""Device serialization, driver context, live status, shared read helpers (REST + MCP + assistant)."""
from __future__ import annotations

import copy
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.drivers.base import DeviceContext
from app.drivers.registry import get_driver
from app.errors import err
from app.models import Alert, Device, Site, Tenant
from app.security import decrypt_json
from app.services import readings as rd


def poll_interval(driver_code: str) -> int:
    d = get_driver(driver_code)
    return d.poll_interval if d else 60


def is_online(device: Device, now: datetime | None = None) -> bool:
    """Online = data newer than 3x the driver's poll interval."""
    if device.last_seen is None:
        return False
    now = now or clock.utcnow()
    return (now - device.last_seen) < timedelta(seconds=3 * poll_interval(device.driver))


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def device_out(d: Device) -> dict[str, Any]:
    return {"id": str(d.id), "site_id": str(d.site_id), "name": d.name, "kind": d.kind, "driver": d.driver,
            "model": d.model, "serial": d.serial, "online": is_online(d), "last_seen": iso(d.last_seen),
            "last_metrics": d.last_metrics, "battery_capacity_wh": d.battery_capacity_wh,
            "created_at": iso(d.created_at)}


def live_out(d: Device) -> dict[str, Any]:
    return {"device_id": str(d.id), "ts": iso(d.last_seen), "online": is_online(d), "metrics": d.last_metrics or {},
            "raw": d.last_raw or {}}


async def device_tz(db: AsyncSession, d: Device) -> str:
    tz = (await db.execute(select(Site.timezone).where(Site.id == d.site_id))).scalar_one_or_none()
    if tz:
        return tz
    t = await db.get(Tenant, d.tenant_id)
    return t.timezone if t else "Asia/Damascus"


async def load_ctx(db: AsyncSession, d: Device) -> DeviceContext:
    creds = decrypt_json(d.credentials_enc) if d.credentials_enc else {}
    return DeviceContext(id=str(d.id), external_id=d.external_id, credentials=creds, state=copy.deepcopy(d.state or {}),
                         battery_capacity_wh=d.battery_capacity_wh, timezone=await device_tz(db, d),
                         serial=d.serial, model=d.model, name=d.name)


# ---- read helpers shared by REST / MCP / assistant -----------------------------------------------------------
async def list_devices(db: AsyncSession, tenant_id: uuid.UUID) -> list[Device]:
    return list((await db.execute(select(Device).where(Device.tenant_id == tenant_id)
                                  .order_by(Device.created_at))).scalars())


async def get_device(db: AsyncSession, tenant_id: uuid.UUID, device_id: str) -> Device:
    from app.deps import get_scoped
    return await get_scoped(db, Device, device_id, tenant_id)


async def history_summary(db: AsyncSession, d: Device, max_days: int, metric: str, hours: float) -> dict[str, Any]:
    hours = max(0.25, min(float(hours), 24 * 90))
    now = clock.utcnow()
    frm, to = rd.parse_range(now - timedelta(hours=hours), now, max_days)
    span_h = (to - frm).total_seconds() / 3600
    bucket = "1m" if span_h <= 3 else "5m" if span_h <= 24 else "15m" if span_h <= 24 * 7 else "1h"
    tz = await device_tz(db, d)
    h = await rd.history(db, d.id, tz, frm, to, [metric], bucket)
    pts = h["series"][metric]
    vals = [p[1] for p in pts]
    step = max(1, len(pts) // 48)
    return {"metric": metric, "hours": round(span_h, 2), "bucket": h["bucket"], "points": len(pts),
            "min": min(vals) if vals else None, "max": max(vals) if vals else None,
            "avg": round(sum(vals) / len(vals), 3) if vals else None, "latest": vals[-1] if vals else None,
            "series": pts[::step]}


def alert_out(a: Alert) -> dict[str, Any]:
    return {"id": str(a.id), "device_id": str(a.device_id) if a.device_id else None, "device_name": a.device_name,
            "type": a.type, "severity": a.severity, "title": a.title, "title_ar": a.title_ar, "body": a.body,
            "body_ar": a.body_ar, "created_at": iso(a.created_at), "read": a.read}


async def recent_alerts(db: AsyncSession, tenant_id: uuid.UUID, limit: int = 10, device_id: uuid.UUID | None = None) -> list[Alert]:
    q = select(Alert).where(Alert.tenant_id == tenant_id)
    if device_id:
        q = q.where(Alert.device_id == device_id)
    return list((await db.execute(q.order_by(Alert.created_at.desc()).limit(max(1, min(limit, 100))))).scalars())
