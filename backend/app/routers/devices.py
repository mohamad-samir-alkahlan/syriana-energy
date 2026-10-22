from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import Principal, current_principal, get_scoped, require_feature, require_roles
from app.drivers.base import DriverError
from app.drivers.registry import all_drivers, get_driver
from app.errors import err
from app.models import Command, Device, Site
from app.security import decrypt_json, encrypt_json
from app.services import control, polling
from app.services import devices as dv
from app.services import readings as rd
from app.services.tenants import family_device_count, valid_tz

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["devices"])
WRITERS = ("owner", "admin")


# ------------------------------------------------------------------ sites
class SiteIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    timezone: str | None = None


class SitePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    timezone: str | None = None


def site_out(s: Site, devices: list[Device]) -> dict:
    return {"id": str(s.id), "name": s.name, "timezone": s.timezone, "devices": [dv.device_out(d) for d in devices]}


@router.get("/sites")
async def list_sites(p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    sites = (await db.execute(select(Site).where(Site.tenant_id == p.tenant.id).order_by(Site.created_at))).scalars().all()
    devs = await dv.list_devices(db, p.tenant.id)
    return [site_out(s, [d for d in devs if d.site_id == s.id]) for s in sites]


@router.post("/sites", status_code=201)
async def create_site(body: SiteIn, p: Principal = Depends(require_roles(*WRITERS)), db: AsyncSession = Depends(get_db, scope="function")):
    tz = body.timezone or p.tenant.timezone
    if not valid_tz(tz):
        raise err(422, "validation_error", "Unknown timezone")
    s = Site(tenant_id=p.tenant.id, name=body.name.strip(), timezone=tz)
    db.add(s)
    await db.flush()
    return site_out(s, [])


@router.patch("/sites/{sid}")
async def patch_site(sid: str, body: SitePatch, p: Principal = Depends(require_roles(*WRITERS)), db: AsyncSession = Depends(get_db, scope="function")):
    s = await get_scoped(db, Site, sid, p.tenant.id)
    if body.name is not None:
        s.name = body.name.strip()
    if body.timezone is not None:
        if not valid_tz(body.timezone):
            raise err(422, "validation_error", "Unknown timezone")
        s.timezone = body.timezone
    devs = [d for d in await dv.list_devices(db, p.tenant.id) if d.site_id == s.id]
    return site_out(s, devs)


@router.delete("/sites/{sid}", status_code=204)
async def delete_site(sid: str, p: Principal = Depends(require_roles(*WRITERS)), db: AsyncSession = Depends(get_db, scope="function")):
    s = await get_scoped(db, Site, sid, p.tenant.id)
    n = (await db.execute(select(func.count(Device.id)).where(Device.site_id == s.id))).scalar_one()
    if n:
        raise err(409, "site_not_empty")
    await db.delete(s)


# ------------------------------------------------------------------ drivers / discovery
@router.get("/drivers")
async def drivers(p: Principal = Depends(current_principal)):
    return [d.info() for d in all_drivers()]


class DiscoverIn(BaseModel):
    driver: str
    credentials: dict[str, Any] = Field(default_factory=dict)


def _driver_or_400(code: str):
    d = get_driver(code)
    if d is None:
        raise err(400, "unknown_driver")
    return d


def _check_credentials(driver, creds: dict[str, Any]) -> None:
    missing = [f["key"] for f in driver.credential_fields if f.get("required") and not creds.get(f["key"])]
    if missing:
        raise err(422, "validation_error", f"Missing credentials: {', '.join(missing)}")


def _driver_failure(e: DriverError):
    if e.code in ("auth_failed", "bad_credentials"):
        return err(400, "integration_auth_failed", f"Login to the device cloud failed: {e.message}")
    return err(502, "device_error", e.message)


@router.post("/integrations/discover")
async def discover(body: DiscoverIn, p: Principal = Depends(require_roles(*WRITERS)), db: AsyncSession = Depends(get_db, scope="function")):
    driver = _driver_or_400(body.driver)
    if not driver.supports_discovery:
        raise err(400, "bad_request", "Driver does not support discovery")
    _check_credentials(driver, body.credentials)
    try:
        found = await driver.discover(body.credentials)
    except DriverError as e:
        raise _driver_failure(e)
    token = encrypt_json({"tenant_id": str(p.tenant.id), "driver": body.driver, "credentials": body.credentials})
    return {"integration_token": token, "devices": [d.to_dict() for d in found]}


class DeviceIn(BaseModel):
    site_id: str
    driver: str
    integration_token: str | None = None
    credentials: dict[str, Any] | None = None
    external_id: str = Field(min_length=1, max_length=300)
    name: str = Field(min_length=1, max_length=200)


class DevicePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    battery_capacity_wh: float | None = Field(default=None, ge=500, le=500000)


@router.post("/devices", status_code=201)
async def create_device(body: DeviceIn, p: Principal = Depends(require_roles(*WRITERS)), db: AsyncSession = Depends(get_db, scope="function")):
    driver = _driver_or_400(body.driver)
    site = await get_scoped(db, Site, body.site_id, p.tenant.id)
    creds: dict[str, Any] = {}
    if body.integration_token:
        try:
            data = decrypt_json(body.integration_token, ttl=1800)
        except ValueError:
            raise err(400, "integration_token_invalid")
        if data.get("tenant_id") != str(p.tenant.id) or data.get("driver") != body.driver:
            raise err(400, "integration_token_invalid")
        creds = data.get("credentials") or {}
    elif body.credentials is not None:
        creds = body.credentials
    _check_credentials(driver, creds)
    if await family_device_count(db, p.tenant) >= p.plan.max_devices:
        raise err(403, "plan_limit", max_devices=p.plan.max_devices)
    model, serial = driver.identify(body.external_id)
    d = Device(tenant_id=p.tenant.id, site_id=site.id, name=body.name.strip(), kind=driver.kind, driver=driver.code,
               model=model, serial=serial, external_id=body.external_id, credentials_enc=encrypt_json(creds) if creds else None,
               state={}, online=False)
    db.add(d)
    try:
        await db.flush()
    except IntegrityError:
        raise err(409, "device_exists")
    await control.audit(db, control.Actor(p.tenant.id, p.user.id if p.user else None, p.actor_name, "rest"),
                        "device.create", str(d.id), {"driver": d.driver, "external_id": d.external_id})
    try:  # first reading right away so the dashboard is not empty
        await asyncio.wait_for(polling.poll_device(db, d.id), 20)
    except Exception:  # noqa: BLE001
        log.warning("initial poll for new device failed", exc_info=True)
    return dv.device_out(d)


@router.get("/devices")
async def list_all_devices(p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    return [dv.device_out(d) for d in await dv.list_devices(db, p.tenant.id)]


@router.get("/devices/{did}")
async def get_device(did: str, p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    return dv.device_out(await dv.get_device(db, p.tenant.id, did))


@router.patch("/devices/{did}")
async def patch_device(did: str, body: DevicePatch, p: Principal = Depends(require_roles(*WRITERS)), db: AsyncSession = Depends(get_db, scope="function")):
    d = await dv.get_device(db, p.tenant.id, did)
    if body.name is not None:
        d.name = body.name.strip()
    if body.battery_capacity_wh is not None:
        d.battery_capacity_wh = body.battery_capacity_wh
    return dv.device_out(d)


@router.delete("/devices/{did}", status_code=204)
async def delete_device(did: str, p: Principal = Depends(require_roles(*WRITERS)), db: AsyncSession = Depends(get_db, scope="function")):
    d = await dv.get_device(db, p.tenant.id, did)
    await control.audit(db, control.Actor(p.tenant.id, p.user.id if p.user else None, p.actor_name, "rest"),
                        "device.delete", str(d.id), {"name": d.name})
    await db.delete(d)


# ------------------------------------------------------------------ live / history / energy
@router.get("/devices/{did}/live")
async def live(did: str, p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    return dv.live_out(await dv.get_device(db, p.tenant.id, did))


@router.get("/devices/{did}/history")
async def history(did: str, from_: datetime | None = Query(None, alias="from"), to: datetime | None = None,
                  metrics: str = "pv_power,load_power,battery_soc", bucket: str = "5m",
                  p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    d = await dv.get_device(db, p.tenant.id, did)
    names = [m.strip() for m in metrics.split(",") if m.strip()]
    if not names or len(names) > 12:
        raise err(400, "bad_request", "metrics must list 1-12 metric names")
    if from_ is not None and from_.tzinfo is None:
        from_ = from_.replace(tzinfo=timezone.utc)
    if to is not None and to.tzinfo is None:
        to = to.replace(tzinfo=timezone.utc)
    frm, to2 = rd.parse_range(from_, to, p.plan.history_days)
    return await rd.history(db, d.id, await dv.device_tz(db, d), frm, to2, names, bucket, dv.poll_interval(d.driver))


@router.get("/devices/{did}/energy")
async def energy(did: str, days: int = Query(30, ge=1, le=366), p: Principal = Depends(current_principal),
                 db: AsyncSession = Depends(get_db, scope="function")):
    d = await dv.get_device(db, p.tenant.id, did)
    return await rd.energy_days(db, d, await dv.device_tz(db, d), days, p.plan.history_days)


@router.get("/devices/{did}/today")
async def today(did: str, p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    d = await dv.get_device(db, p.tenant.id, did)
    return await rd.today_summary(db, d, await dv.device_tz(db, d))


# ------------------------------------------------------------------ control
class SettingIn(BaseModel):
    key: str
    value: Any
    confirm: bool | None = None


@router.get("/devices/{did}/settings")
async def get_settings(did: str, p: Principal = Depends(require_feature("control", WRITERS)), db: AsyncSession = Depends(get_db, scope="function")):
    d = await dv.get_device(db, p.tenant.id, did)
    return [s.to_dict() for s in await control.list_settings(db, d)]


@router.post("/devices/{did}/settings")
async def set_setting(did: str, body: SettingIn, p: Principal = Depends(require_feature("control", WRITERS)),
                      db: AsyncSession = Depends(get_db, scope="function")):
    d = await dv.get_device(db, p.tenant.id, did)
    actor = control.Actor(p.tenant.id, p.user.id if p.user else None, p.actor_name, "rest")
    cmd = await control.change_setting(db, actor, d, body.key, body.value, body.confirm)
    return control.command_out(cmd)


@router.get("/devices/{did}/commands")
async def commands(did: str, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                   p: Principal = Depends(require_feature("control", WRITERS)), db: AsyncSession = Depends(get_db, scope="function")):
    d = await dv.get_device(db, p.tenant.id, did)
    q = select(Command).where(Command.device_id == d.id, Command.tenant_id == p.tenant.id)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (await db.execute(q.order_by(Command.created_at.desc()).limit(limit).offset(offset))).scalars().all()
    return {"items": [control.command_out(c) for c in rows], "total": total}
