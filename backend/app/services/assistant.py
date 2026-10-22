"""AI assistant: Claude Messages API via httpx with read-only tools (grounded in the tenant's own data)."""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.config import settings
from app.errors import AppError, err
from app.models import Device
from app.services import control
from app.services import devices as dv
from app.services import readings as rd

log = logging.getLogger(__name__)
MAX_TOOL_ROUNDS = 5

TOOLS: list[dict[str, Any]] = [
    {"name": "get_live_status", "description": "Current live status of a solar inverter/battery system: battery SOC, "
     "PV, load, grid availability, mode, voltages. Use for 'how is it now' questions.",
     "input_schema": {"type": "object", "properties": {"device_id": {"type": "string"}}, "required": []}},
    {"name": "get_today_summary", "description": "Today's energy totals (solar, load, grid kWh), grid outages and the "
     "estimated battery runtime in hours.",
     "input_schema": {"type": "object", "properties": {"device_id": {"type": "string"}}, "required": []}},
    {"name": "get_history_summary", "description": "Min/max/avg and a downsampled series for one metric over the last N hours.",
     "input_schema": {"type": "object", "properties": {
         "device_id": {"type": "string"}, "metric": {"type": "string", "description": "e.g. pv_power, load_power, battery_soc, grid_available"},
         "hours": {"type": "number"}}, "required": ["metric"]}},
    {"name": "list_recent_alerts", "description": "Most recent alerts/notifications for the account.",
     "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}, "required": []}},
    {"name": "get_settings", "description": "Current inverter settings (output priority, charger priority, charge current, buzzer) "
     "with allowed values. Read-only.",
     "input_schema": {"type": "object", "properties": {"device_id": {"type": "string"}}, "required": []}},
]

SYSTEM_PROMPT = """You are the assistant of "Syriana Energy", an app that monitors home solar systems (hybrid inverter + lithium battery, usually 24V) in Syria.
Rules:
- Answer in the SAME language the user writes in. If unclear, use Arabic. Arabic replies must be simple, clear, Syrian-friendly Arabic (not stiff classical Arabic). The user's interface language is: {locale}.
- Use ONLY data returned by your tools. Never invent numbers, times or device states. If the data does not contain the answer, say so briefly.
- Call tools before answering anything about the system's current state, history, alerts or settings.
- You are read-only: you cannot change settings. If asked to change something, explain which setting to change in the app (Control page) and that the user must confirm it there.
- Be concise. Give numbers with units (W, kWh, %, V). Mention grid outages in plain words ("الدولة قاطعة").
- Battery runtime estimates are approximate; say so.
Current UTC time: {now}."""


async def run_tool(db: AsyncSession, tenant_id: uuid.UUID, history_days: int, name: str, args: dict[str, Any],
                   default_device_id: str | None) -> Any:
    async def resolve() -> Device | dict[str, str]:
        did = args.get("device_id") or default_device_id
        if did:
            try:
                return await dv.get_device(db, tenant_id, did)
            except AppError:
                return {"error": "device not found"}
        devs = await dv.list_devices(db, tenant_id)
        return devs[0] if devs else {"error": "no devices registered"}

    if name == "list_recent_alerts":
        items = await dv.recent_alerts(db, tenant_id, int(args.get("limit") or 10))
        return [{k: a[k] for k in ("type", "severity", "title", "body", "device_name", "created_at")}
                for a in map(dv.alert_out, items)]
    d = await resolve()
    if isinstance(d, dict):
        return d
    if name == "get_live_status":
        return {"device": d.name, **dv.live_out(d)}
    if name == "get_today_summary":
        return {"device": d.name, **(await rd.today_summary(db, d, await dv.device_tz(db, d)))}
    if name == "get_history_summary":
        try:
            return {"device": d.name, **(await dv.history_summary(db, d, history_days, str(args.get("metric", "")),
                                                                    float(args.get("hours") or 24)))}
        except AppError as e:
            return {"error": e.message}
    if name == "get_settings":
        try:
            return {"device": d.name, "settings": [s.to_dict() for s in await control.list_settings(db, d)]}
        except AppError as e:
            return {"error": e.message}
    return {"error": f"unknown tool {name}"}


async def _call(client: httpx.AsyncClient, body: dict[str, Any]) -> dict[str, Any]:
    try:
        r = await client.post(f"{settings.anthropic_base_url.rstrip('/')}/v1/messages", json=body, headers={
            "x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    except httpx.HTTPError as e:
        raise err(502, "ai_error", f"AI provider unreachable: {e.__class__.__name__}")
    if r.status_code != 200:
        log.warning("anthropic error %s: %s", r.status_code, r.text[:300])
        raise err(502, "ai_error", f"AI provider error ({r.status_code})")
    return r.json()


async def chat(db: AsyncSession, tenant_id: uuid.UUID, history_days: int, locale: str, messages: list[dict[str, str]],
               device_id: str | None, transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    if not settings.anthropic_api_key:
        raise err(503, "ai_unavailable")
    system = SYSTEM_PROMPT.format(locale="Arabic" if locale == "ar" else "English", now=clock.utcnow().isoformat())
    msgs: list[dict[str, Any]] = [{"role": m["role"], "content": m["content"]} for m in messages]
    used: list[str] = []
    async with httpx.AsyncClient(timeout=60, transport=transport) as client:
        base = {"model": settings.anthropic_model, "max_tokens": 1024, "system": system, "tools": TOOLS}
        for round_i in range(MAX_TOOL_ROUNDS + 1):
            final = round_i == MAX_TOOL_ROUNDS
            body = {**base, "messages": msgs, **({"tool_choice": {"type": "none"}} if final else {})}
            resp = await _call(client, body)
            blocks = resp.get("content") or []
            uses = [b for b in blocks if b.get("type") == "tool_use"]
            if resp.get("stop_reason") != "tool_use" or not uses or final:
                text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
                return {"reply": text, "used_tools": used}
            msgs.append({"role": "assistant", "content": blocks})
            results = []
            for u in uses:
                used.append(u["name"])
                try:
                    out = await run_tool(db, tenant_id, history_days, u["name"], u.get("input") or {}, device_id)
                except Exception as e:  # noqa: BLE001
                    log.exception("assistant tool failed")
                    out = {"error": f"tool failed: {type(e).__name__}"}
                results.append({"type": "tool_result", "tool_use_id": u["id"],
                                "content": json.dumps(out, ensure_ascii=False, default=str)[:12000]})
            msgs.append({"role": "user", "content": results})
    return {"reply": "", "used_tools": used}
