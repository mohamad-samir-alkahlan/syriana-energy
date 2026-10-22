from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import VERSION, settings
from app.errors import install_handlers
from app.routers import alerts, auth, automations, devices, misc, tenant

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("syriana")


class Dispatcher:
    """Outermost ASGI app: /mcp -> MCP gateway, everything else -> FastAPI (which owns lifespan)."""

    def __init__(self, api: FastAPI):
        self.api = api
        self.mcp_gateway = None

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and (scope["path"] == "/mcp" or scope["path"].startswith("/mcp/")):
            if self.mcp_gateway is None:
                body = json.dumps({"error": {"code": "mcp_unavailable", "message": "MCP server not started",
                                            "message_ar": "خادم MCP غير مشغّل"}}).encode()
                await send({"type": "http.response.start", "status": 503,
                            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
            await self.mcp_gateway(scope, receive, send)
            return
        await self.api(scope, receive, send)


def create_api() -> tuple[FastAPI, Dispatcher]:
    settings.validate_production()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from app.mcp_server import MCPGateway, create_mcp
        from app.startup import ensure_hypertable
        await ensure_hypertable()
        mcp = create_mcp()
        gateway = MCPGateway(mcp.streamable_http_app())
        dispatcher.mcp_gateway = gateway
        async with mcp.session_manager.run():
            log.info("Syriana Energy API %s started (env=%s)", VERSION, settings.app_env)
            yield
        dispatcher.mcp_gateway = None

    docs = settings.api_docs if settings.api_docs is not None else settings.app_env != "production"
    api = FastAPI(title="Syriana Energy API", version=VERSION, docs_url="/api/docs" if docs else None, redoc_url=None,
                  openapi_url="/api/openapi.json" if docs else None, lifespan=lifespan,
                  description="Multi-tenant solar monitoring & control. MCP is served at /mcp (Bearer API key).")
    install_handlers(api)
    for r in (misc.public, auth.router, tenant.router, devices.router, alerts.router, automations.router,
              misc.assistant, misc.keys, misc.billing, misc.admin):
        api.include_router(r)
    dispatcher = Dispatcher(api)
    return api, dispatcher


api, app = create_api()
