from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import Principal, get_scoped, require_feature
from app.errors import err
from app.models import Automation, Device
from app.services.automations import validate_spec
from app.services import devices as dv

router = APIRouter(prefix="/api/automations", tags=["automations"])
WRITERS = ("owner", "admin")


def auto_out(a: Automation) -> dict:
    return {"id": str(a.id), "name": a.name, "enabled": a.enabled, "device_id": str(a.device_id) if a.device_id else None,
            "conditions": a.conditions or [], "grid": a.grid, "actions": a.actions or [],
            "recover_conditions": a.recover_conditions or [], "recover_actions": a.recover_actions or [],
            "state": a.state, "last_triggered_at": dv.iso(a.last_triggered_at)}


class AutoIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    device_id: str | None = None
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    grid: str = "any"
    actions: list[dict[str, Any]] = Field(default_factory=list)
    recover_conditions: list[dict[str, Any]] = Field(default_factory=list)
    recover_actions: list[dict[str, Any]] = Field(default_factory=list)


class AutoPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    enabled: bool | None = None
    device_id: str | None = None
    conditions: list[dict[str, Any]] | None = None
    grid: str | None = None
    actions: list[dict[str, Any]] | None = None
    recover_conditions: list[dict[str, Any]] | None = None
    recover_actions: list[dict[str, Any]] | None = None


def _validate(a_conds, a_actions, grid, r_conds, r_actions) -> None:
    for conds, acts in ((a_conds, a_actions), (r_conds, r_actions)):
        msg = validate_spec(conds, acts, grid)
        if msg:
            raise err(422, "validation_error", msg)


async def _check_device(db: AsyncSession, p: Principal, device_id: str | None):
    if device_id:
        return (await get_scoped(db, Device, device_id, p.tenant.id)).id
    return None


@router.get("")
async def list_automations(p: Principal = Depends(require_feature("automations")), db: AsyncSession = Depends(get_db, scope="function")):
    rows = (await db.execute(select(Automation).where(Automation.tenant_id == p.tenant.id).order_by(Automation.created_at))).scalars()
    return [auto_out(a) for a in rows]


@router.post("", status_code=201)
async def create_automation(body: AutoIn, p: Principal = Depends(require_feature("automations", WRITERS)),
                            db: AsyncSession = Depends(get_db, scope="function")):
    if not body.conditions:
        raise err(422, "validation_error", "At least one condition is required")
    _validate(body.conditions, body.actions, body.grid, body.recover_conditions, body.recover_actions)
    a = Automation(tenant_id=p.tenant.id, name=body.name.strip(), enabled=body.enabled,
                   device_id=await _check_device(db, p, body.device_id), conditions=body.conditions, grid=body.grid,
                   actions=body.actions, recover_conditions=body.recover_conditions, recover_actions=body.recover_actions,
                   state="idle")
    db.add(a)
    await db.flush()
    return auto_out(a)


@router.get("/{aid}")
async def get_automation(aid: str, p: Principal = Depends(require_feature("automations")), db: AsyncSession = Depends(get_db, scope="function")):
    return auto_out(await get_scoped(db, Automation, aid, p.tenant.id))


@router.patch("/{aid}")
async def patch_automation(aid: str, body: AutoPatch, p: Principal = Depends(require_feature("automations", WRITERS)),
                           db: AsyncSession = Depends(get_db, scope="function")):
    a = await get_scoped(db, Automation, aid, p.tenant.id)
    data = body.model_dump(exclude_unset=True)
    if "device_id" in data:
        a.device_id = await _check_device(db, p, data.pop("device_id"))
    for k, v in data.items():
        if v is not None:
            setattr(a, k, v.strip() if k == "name" else v)
    _validate(a.conditions, a.actions, a.grid, a.recover_conditions, a.recover_actions)
    if "enabled" in data and data["enabled"] is False:
        a.state = "idle"
    return auto_out(a)


@router.delete("/{aid}", status_code=204)
async def delete_automation(aid: str, p: Principal = Depends(require_feature("automations", WRITERS)),
                            db: AsyncSession = Depends(get_db, scope="function")):
    await db.delete(await get_scoped(db, Automation, aid, p.tenant.id))
