"""MCP (streamable HTTP) endpoint mounted at /mcp. Auth: Authorization: Bearer se_live_... (needs the `api` feature)."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from app.db import SessionLocal
from app.deps import Principal, principal_from_api_key
from app.errors import AppError, err
from app.security import API_KEY_PREFIX
from app.services import control
from app.services import devices as dv
from app.services import readings as rd


def _token_from_headers(headers) -> str:
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer ") and auth[7:].strip().startswith(API_KEY_PREFIX):
        return auth[7:].strip()
    raise err(401, "unauthorized")


@asynccontextmanager
async def _authed(ctx: Context):
    """Yields (db, principal). Every query below is scoped to principal.tenant."""
    try:
        req = ctx.request_context.request
        token = _token_from_headers(req.headers)
        async with SessionLocal() as db:
            p = await principal_from_api_key(db, token)
            try:
                yield db, p
                await db.commit()
            except AppError as e:
                await db.commit()  # keep audit rows written before the error
                raise ToolError(f"{e.code}: {e.message}") from e
    except AppError as e:
        raise ToolError(f"{e.code}: {e.message}") from e


def _j(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, default=str)


def create_mcp() -> FastMCP:
    mcp = FastMCP("Syriana Energy", instructions="Monitor and control a home solar system (inverter + battery).",
                  stateless_http=True, json_response=True, streamable_http_path="/mcp",
                  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))

    @mcp.tool()
    async def list_devices(ctx: Context) -> str:
        """List the devices (inverters/batteries) of this account with their last known metrics."""
        async with _authed(ctx) as (db, p):
            return _j([dv.device_out(d) for d in await dv.list_devices(db, p.tenant.id)])

    @mcp.tool()
    async def get_live_status(ctx: Context, device_id: str) -> str:
        """Live status of a device: battery SOC, PV, load, grid availability, mode, voltages."""
        async with _authed(ctx) as (db, p):
            return _j(dv.live_out(await dv.get_device(db, p.tenant.id, device_id)))

    @mcp.tool()
    async def get_today_summary(ctx: Context, device_id: str) -> str:
        """Today's solar/load/grid energy (kWh), grid outages and estimated battery runtime (hours)."""
        async with _authed(ctx) as (db, p):
            d = await dv.get_device(db, p.tenant.id, device_id)
            return _j(await rd.today_summary(db, d, await dv.device_tz(db, d)))

    @mcp.tool()
    async def get_history(ctx: Context, device_id: str, metric: str, hours: float = 24) -> str:
        """Summary (min/max/avg + downsampled series) of one metric over the last `hours` hours (clamped to the plan)."""
        async with _authed(ctx) as (db, p):
            d = await dv.get_device(db, p.tenant.id, device_id)
            return _j(await dv.history_summary(db, d, p.plan.history_days, metric, hours))

    @mcp.tool()
    async def list_alerts(ctx: Context, limit: int = 20) -> str:
        """Most recent alerts."""
        async with _authed(ctx) as (db, p):
            return _j([dv.alert_out(a) for a in await dv.recent_alerts(db, p.tenant.id, limit)])

    def _need_control(p: Principal) -> None:
        if "control" not in p.plan.features:
            raise err(403, "feature_not_in_plan", feature="control")

    @mcp.tool()
    async def get_settings(ctx: Context, device_id: str) -> str:
        """Current device settings with their allowed values (requires the control feature)."""
        async with _authed(ctx) as (db, p):
            _need_control(p)
            d = await dv.get_device(db, p.tenant.id, device_id)
            return _j([s.to_dict() for s in await control.list_settings(db, d)])

    @mcp.tool()
    async def change_setting(ctx: Context, device_id: str, key: str, value: Any, confirm: bool = False) -> str:
        """Change a device setting. Requires confirm=true. Validated against safe ranges and audit-logged."""
        async with _authed(ctx) as (db, p):
            _need_control(p)
            d = await dv.get_device(db, p.tenant.id, device_id)
            actor = control.Actor(p.tenant.id, None, p.actor_name, "mcp")
            cmd = await control.change_setting(db, actor, d, key, value, confirm)
            return _j(control.command_out(cmd))

    return mcp


class MCPGateway:
    """ASGI wrapper: early 401 for missing/invalid API keys, then hand over to the MCP app."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
            try:
                token = _token_from_headers(headers)
                async with SessionLocal() as db:
                    await principal_from_api_key(db, token)
                    await db.commit()
            except AppError as e:
                body = json.dumps(e.body()).encode()
                await send({"type": "http.response.start", "status": e.status,
                            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.inner(scope, receive, send)
