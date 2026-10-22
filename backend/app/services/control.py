"""Device control: validated, confirmed, audit-logged setting changes (shared by REST, MCP and automations)."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.drivers.base import DriverError, SettingDef
from app.drivers.registry import get_driver
from app.errors import AppError, err
from app.models import AuditLog, Command, Device
from app.services import devices as dv

log = logging.getLogger("audit")


@dataclass
class Actor:
    tenant_id: uuid.UUID
    user_id: uuid.UUID | None
    name: str
    source: str  # rest | mcp | automation


async def audit(db: AsyncSession, actor: Actor | None, action: str, target: str | None = None,
                detail: dict[str, Any] | None = None, tenant_id: uuid.UUID | None = None) -> None:
    db.add(AuditLog(tenant_id=actor.tenant_id if actor else tenant_id, user_id=actor.user_id if actor else None,
                    action=action, target=target, detail={**(detail or {}), **({"source": actor.source, "actor": actor.name} if actor else {})}))
    log.info("audit action=%s target=%s actor=%s detail=%s", action, target, actor.name if actor else None, detail)


def command_out(c: Command) -> dict[str, Any]:
    return {"id": str(c.id), "key": c.key, "old_value": c.old_value, "new_value": c.new_value, "status": c.status,
            "error": c.error, "user_name": c.user_name, "created_at": dv.iso(c.created_at)}


async def list_settings(db: AsyncSession, device: Device) -> list[SettingDef]:
    driver = get_driver(device.driver)
    if driver is None or not driver.supports_control:
        return []
    ctx = await dv.load_ctx(db, device)
    try:
        return await driver.get_settings(ctx)
    except DriverError as e:
        raise err(502, "device_error", f"{e.message}")


async def change_setting(db: AsyncSession, actor: Actor, device: Device, key: str, value: Any, confirm: Any) -> Command:
    if confirm is not True:
        raise err(400, "confirm_required")
    driver = get_driver(device.driver)
    if driver is None or not driver.supports_control:
        raise err(400, "bad_request", "This device does not support control")
    await db.refresh(device, with_for_update=True)  # wait for an in-flight poll, then work on fresh driver state
    ctx = await dv.load_ctx(db, device)
    try:
        defs = {d.key: d for d in await driver.get_settings(ctx)}
    except DriverError as e:
        raise err(502, "device_error", e.message)
    sd = defs.get(key)
    if sd is None:
        raise err(404, "setting_not_found", f"Unknown setting '{key}'")
    try:
        new_value = sd.validate(value)
    except ValueError as e:
        await audit(db, actor, "setting.rejected", str(device.id), {"key": key, "value": value, "reason": str(e)})
        await db.commit()  # keep the audit row even though we answer with an error
        raise err(422, "unsafe_value", str(e))
    cmd = Command(tenant_id=actor.tenant_id, device_id=device.id, user_id=actor.user_id, user_name=actor.name,
                  source=actor.source, key=key, old_value=sd.value, new_value=new_value, status="pending")
    db.add(cmd)
    await db.flush()
    await audit(db, actor, "setting.change", str(device.id), {"key": key, "old": sd.value, "new": new_value, "command": str(cmd.id)})
    try:
        await driver.write_setting(ctx, key, new_value)
        cmd.status = "ok"
        device.state = dict(ctx.state)
    except (DriverError, Exception) as e:  # noqa: BLE001
        cmd.status = "failed"
        cmd.error = str(getattr(e, "message", e))[:500]
    await audit(db, actor, "setting.result", str(device.id), {"command": str(cmd.id), "status": cmd.status, "error": cmd.error})
    await db.flush()
    if cmd.status == "failed":
        await db.commit()
        raise AppError(502, "device_error", f"Command failed: {cmd.error}", extra={"command_id": str(cmd.id)})
    return cmd
