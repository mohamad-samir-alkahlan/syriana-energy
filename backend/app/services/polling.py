"""Poll one device: read via driver, store reading, update device, evaluate alerts + automations."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.drivers.base import DriverError
from app.drivers.registry import all_drivers, get_driver
from app.models import Device, Tenant
from app.services import alerts, automations
from app.services import devices as dv
from app.services import readings as rd
from app.services.tenants import effective_plan

log = logging.getLogger(__name__)
READ_TIMEOUT = 45


async def poll_device(db: AsyncSession, device_id: uuid.UUID, now: datetime | None = None) -> dict[str, Any] | None:
    # row lock: serializes with control commands so driver state (settings) is never overwritten by a stale copy
    device = (await db.execute(select(Device).where(Device.id == device_id).with_for_update())).scalar_one_or_none()
    if device is None:
        return None
    driver = get_driver(device.driver)
    if driver is None:
        device.last_error = f"unknown driver {device.driver}"
        return None
    ctx = await dv.load_ctx(db, device)
    try:
        metrics, raw = await asyncio.wait_for(driver.read(ctx), READ_TIMEOUT)
    except asyncio.TimeoutError:
        device.last_error = "timeout"
        device.online = dv.is_online(device)
        return None
    except DriverError as e:
        device.last_error = f"{e.code}: {e.message}"[:500]
        device.online = dv.is_online(device)
        log.warning("poll %s failed: %s", device.name, device.last_error)
        return None
    except Exception as e:  # noqa: BLE001
        device.last_error = f"{type(e).__name__}: {e}"[:500]
        device.online = dv.is_online(device)
        log.exception("poll %s crashed", device.name)
        return None

    now = now or clock.utcnow()
    await rd.store_reading(db, device.id, now, metrics, raw)
    prev = device.last_metrics
    device.last_seen, device.last_metrics, device.last_raw = now, metrics, raw
    device.state, device.online, device.last_error = dict(ctx.state), True, None
    await db.flush()

    tenant = await db.get(Tenant, device.tenant_id)
    plan = await effective_plan(db, tenant)
    fired = await alerts.process_reading(db, device, tenant, plan, metrics, prev, now)
    events = await automations.run_for_reading(db, device, tenant, plan, metrics, now)
    return {"metrics": metrics, "alerts": fired, "automations": events}


async def refresh_online_flags(db: AsyncSession, now: datetime | None = None) -> None:
    from datetime import timedelta
    now = now or clock.utcnow()
    for drv in all_drivers():
        cut = now - timedelta(seconds=3 * drv.poll_interval)
        await db.execute(update(Device).where(Device.driver == drv.code)
                         .values(online=(Device.last_seen.is_not(None) & (Device.last_seen > cut))))


async def due_devices(db: AsyncSession) -> list[tuple[uuid.UUID, str]]:
    return [(r[0], r[1]) for r in (await db.execute(select(Device.id, Device.driver))).all()]
