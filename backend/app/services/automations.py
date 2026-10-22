"""Automations (load shedding): condition -> actions once on entering, recover_actions once on leaving."""
from __future__ import annotations

import logging
import operator
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.drivers.base import ALL_METRICS
from app.errors import AppError
from app.models import Automation, Device, Tenant
from app.services import alerts, control, notify
from app.services.tenants import EffectivePlan

log = logging.getLogger(__name__)

OPS = {"<": operator.lt, ">": operator.gt, "<=": operator.le, ">=": operator.ge, "==": operator.eq}
GRID_MODES = {"any", "available", "lost"}
ACTION_TYPES = {"notify", "http", "setting"}


def _num(v: Any) -> Any:
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    return v


def conditions_met(metrics: dict[str, Any], conds: list[dict[str, Any]]) -> bool:
    if not conds:
        return False
    for c in conds:
        have = metrics.get(c.get("metric"))
        if have is None:
            return False
        want, op = c.get("value"), OPS.get(c.get("op"))
        if op is None:
            return False
        try:
            if not op(_num(have), _num(want)):
                return False
        except TypeError:
            return False
    return True


def grid_matches(metrics: dict[str, Any], grid: str) -> bool:
    if grid == "any":
        return True
    ga = metrics.get("grid_available")
    return (ga is True) if grid == "available" else (ga is False)


def validate_spec(conds: list[dict[str, Any]], actions: list[dict[str, Any]], grid: str) -> str | None:
    if grid not in GRID_MODES:
        return "grid must be any|available|lost"
    for c in conds:
        if c.get("metric") not in ALL_METRICS or c.get("op") not in OPS or "value" not in c:
            return f"invalid condition {c}"
    for a in actions:
        if a.get("type") not in ACTION_TYPES:
            return f"invalid action {a}"
        if a["type"] == "http" and (a.get("method", "GET").upper() not in ("GET", "POST", "PUT") or not a.get("url")):
            return "http action needs method GET|POST|PUT and url"
        if a["type"] == "setting" and ("key" not in a or "value" not in a):
            return "setting action needs key and value"
    return None


async def _run_actions(db: AsyncSession, a: Automation, tenant: Tenant, plan: EffectivePlan, device: Device,
                       actions: list[dict[str, Any]], now: datetime, phase: str) -> None:
    for act in actions:
        try:
            if act["type"] == "notify":
                await alerts.emit(db, tenant, plan, device, "automation",
                                  {"name": a.name, "message": act.get("message") or f"{a.name} ({phase})"},
                                  ["inapp", "telegram"], now)
            elif act["type"] == "http":
                await notify.transports.http_action(act.get("method", "GET").upper(), act["url"], act.get("body"))
            elif act["type"] == "setting":
                if "control" not in plan.features:
                    raise ValueError("plan has no control feature")
                actor = control.Actor(tenant.id, None, f"automation:{a.name}", "automation")
                await control.change_setting(db, actor, device, act["key"], act["value"], True)
        except (AppError, ValueError, Exception) as e:  # noqa: BLE001
            msg = getattr(e, "message", str(e))
            log.warning("automation %s action %s failed: %s", a.name, act.get("type"), msg)
            await alerts.emit(db, tenant, plan, device, "automation",
                              {"name": a.name, "message": f"Action '{act.get('type')}' failed: {msg}"},
                              ["inapp"], now, severity="warning")


async def run_for_reading(db: AsyncSession, device: Device, tenant: Tenant, plan: EffectivePlan,
                          metrics: dict[str, Any], now: datetime) -> list[tuple[str, str]]:
    """Returns [(automation name, 'triggered'|'recovered')]."""
    if "automations" not in plan.features:
        return []
    autos = list((await db.execute(select(Automation).where(
        Automation.tenant_id == tenant.id, Automation.enabled.is_(True),
        or_(Automation.device_id == device.id, Automation.device_id.is_(None))))).scalars())
    events = []
    for a in autos:
        trig = conditions_met(metrics, a.conditions or []) and grid_matches(metrics, a.grid)
        if a.state != "active":
            if trig:
                a.state, a.last_triggered_at = "active", now
                await _run_actions(db, a, tenant, plan, device, a.actions or [], now, "triggered")
                events.append((a.name, "triggered"))
        else:
            if a.recover_conditions:
                rec = conditions_met(metrics, a.recover_conditions)
            else:
                rec = not trig
            if rec:
                a.state = "idle"
                await _run_actions(db, a, tenant, plan, device, a.recover_actions or [], now, "recovered")
                events.append((a.name, "recovered"))
    await db.flush()
    return events
