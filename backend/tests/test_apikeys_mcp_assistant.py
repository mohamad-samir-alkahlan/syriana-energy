import hashlib
import json

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from sqlalchemy import select

from app.db import SessionLocal
from app.main import api, app
from app.models import ApiKey, Command
from app.routers import misc
from tests.conftest import add_demo_device, make_client, register, set_plan


# ------------------------------------------------------------------ API keys
async def test_api_key_lifecycle(client):
    me = await register(client)
    assert (await client.post("/api/api-keys", json={"name": "k"})).status_code == 403  # free plan
    await set_plan(me["tenant"]["id"], "home")
    dev = await add_demo_device(client)
    r = await client.post("/api/api-keys", json={"name": "grafana"})
    assert r.status_code == 201
    key = r.json()
    assert key["key"].startswith("se_live_") and set(key) == {"id", "name", "key"}
    listed = (await client.get("/api/api-keys")).json()
    assert listed[0]["name"] == "grafana" and "key" not in listed[0] and key["key"].startswith(listed[0]["prefix"])
    # only the sha256 is stored
    async with SessionLocal() as s:
        row = (await s.execute(select(ApiKey))).scalar_one()
    assert row.key_hash == hashlib.sha256(key["key"].encode()).hexdigest() and key["key"] not in (row.key_hash, row.prefix)

    m = make_client()
    h = {"Authorization": f"Bearer {key['key']}"}
    r = await m.get("/api/devices", headers=h)
    assert r.status_code == 200 and r.json()[0]["id"] == dev["id"]
    assert (await m.get(f"/api/devices/{dev['id']}/live", headers=h)).json()["metrics"]
    assert (await m.get("/api/devices", headers={"Authorization": "Bearer se_live_wrong"})).status_code == 401
    assert (await m.get("/api/devices", headers={"Authorization": "Bearer abc"})).status_code == 401
    # keys cannot mint more keys, nor create or change users
    assert (await m.post("/api/api-keys", json={"name": "x"}, headers=h)).status_code == 403
    r = await m.post("/api/users", headers=h, json={"email": "evil@example.com", "name": "x", "role": "admin",
                                                     "password": "password123"})
    assert r.status_code == 403
    assert (await m.delete(f"/api/users/{me['user']['id']}", headers=h)).status_code == 403
    # control through a key is audited with the key's name
    r = await m.post(f"/api/devices/{dev['id']}/settings", headers=h, json={"key": "buzzer", "value": False, "confirm": True})
    assert r.status_code == 200 and r.json()["user_name"] == "API key: grafana"
    # downgrade => key stops working
    await set_plan(me["tenant"]["id"], "free")
    r = await m.get("/api/devices", headers=h)
    assert r.status_code == 403 and r.json()["error"]["code"] == "feature_not_in_plan"
    await set_plan(me["tenant"]["id"], "home")
    assert (await client.delete(f"/api/api-keys/{key['id']}")).status_code == 204
    assert (await m.get("/api/devices", headers=h)).status_code == 401
    await m.aclose()


# ------------------------------------------------------------------ MCP
def _factory(headers=None, timeout=None, auth=None):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=headers,
                             timeout=timeout or 30, auth=auth, follow_redirects=True)


async def test_mcp_without_key_is_401(client):
    async with api.router.lifespan_context(api):
        r = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
        r = await client.post("/mcp", json={}, headers={"Authorization": "Bearer se_live_nope"})
        assert r.status_code == 401


async def test_mcp_tools_list_and_calls(client):
    me = await register(client)
    await set_plan(me["tenant"]["id"], "pro")
    dev = await add_demo_device(client, "MCP Demo")
    key = (await client.post("/api/api-keys", json={"name": "claude"})).json()["key"]
    other = make_client()
    mo = await register(other)
    await set_plan(mo["tenant"]["id"], "pro")
    odev = await add_demo_device(other, "Other tenant device")

    async with api.router.lifespan_context(api):
        async with streamablehttp_client("http://test/mcp", headers={"Authorization": f"Bearer {key}"}, httpx_client_factory=_factory) as (rd, wr, _):
            async with ClientSession(rd, wr) as s:
                await s.initialize()
                tools = {t.name for t in (await s.list_tools()).tools}
                assert tools == {"list_devices", "get_live_status", "get_today_summary", "get_history", "list_alerts", "get_settings", "change_setting"}

                devs = json.loads((await s.call_tool("list_devices", {})).content[0].text)
                assert [d["name"] for d in devs] == ["MCP Demo"]
                live = json.loads((await s.call_tool("get_live_status", {"device_id": dev["id"]})).content[0].text)
                assert live["device_id"] == dev["id"] and "battery_soc" in live["metrics"] and live["online"] is True
                today = json.loads((await s.call_tool("get_today_summary", {"device_id": dev["id"]})).content[0].text)
                assert {"pv_kwh", "load_kwh", "grid_outages", "battery_runtime_hours"} <= set(today)
                hist = json.loads((await s.call_tool("get_history", {"device_id": dev["id"], "metric": "battery_soc", "hours": 2})).content[0].text)
                assert hist["metric"] == "battery_soc"
                assert isinstance((await s.call_tool("list_alerts", {"limit": 5})).content[0].text, str)
                st = json.loads((await s.call_tool("get_settings", {"device_id": dev["id"]})).content[0].text)
                assert {x["key"] for x in st} >= {"output_priority", "max_ac_charge_current"}

                # tenant scoping: another tenant's device is invisible
                r = await s.call_tool("get_live_status", {"device_id": odev["id"]})
                assert r.isError and "not_found" in r.content[0].text

                # change_setting: confirm required, validated, audited like REST
                r = await s.call_tool("change_setting", {"device_id": dev["id"], "key": "buzzer", "value": False})
                assert r.isError and "confirm_required" in r.content[0].text
                r = await s.call_tool("change_setting", {"device_id": dev["id"], "key": "max_ac_charge_current", "value": 999, "confirm": True})
                assert r.isError and "unsafe_value" in r.content[0].text
                r = await s.call_tool("change_setting", {"device_id": dev["id"], "key": "max_ac_charge_current", "value": 40, "confirm": True})
                assert not r.isError and json.loads(r.content[0].text)["new_value"] == 40

    async with SessionLocal() as db:
        cmd = (await db.execute(select(Command))).scalar_one()
    assert cmd.source == "mcp" and cmd.user_name == "API key: claude" and cmd.new_value == 40
    assert (await client.get(f"/api/devices/{dev['id']}/settings")).json()[2]["value"] == 40
    await other.aclose()


async def test_mcp_requires_api_feature_and_control_feature(client):
    me = await register(client)
    await set_plan(me["tenant"]["id"], "home")
    dev = await add_demo_device(client)
    key = (await client.post("/api/api-keys", json={"name": "k"})).json()["key"]
    # plan with api but without control
    from app.models import Plan
    async with SessionLocal() as s:
        p = await s.get(Plan, "home")
        p.features = ["api"]
        await s.commit()
    async with api.router.lifespan_context(api):
        async with streamablehttp_client("http://test/mcp", headers={"Authorization": f"Bearer {key}"}, httpx_client_factory=_factory) as (rd, wr, _):
            async with ClientSession(rd, wr) as s:
                await s.initialize()
                r = await s.call_tool("change_setting", {"device_id": dev["id"], "key": "buzzer", "value": False, "confirm": True})
                assert r.isError and "feature_not_in_plan" in r.content[0].text
                r = await s.call_tool("get_live_status", {"device_id": dev["id"]})
                assert not r.isError
        await set_plan(me["tenant"]["id"], "free")
        r = await client.post("/mcp", json={}, headers={"Authorization": f"Bearer {key}"})
        assert r.status_code == 403 and r.json()["error"]["code"] == "feature_not_in_plan"
    async with SessionLocal() as s:
        p = await s.get(Plan, "home")
        p.features = ["control", "ai", "email", "webhook", "automations", "api"]
        await s.commit()


# ------------------------------------------------------------------ assistant
def _anthropic(handler, monkeypatch):
    calls = []

    def wrapped(req: httpx.Request):
        body = json.loads(req.content)
        calls.append({"headers": dict(req.headers), "body": body, "url": str(req.url)})
        return handler(body, len(calls))
    monkeypatch.setattr(misc, "assistant_transport", httpx.MockTransport(wrapped))
    return calls


async def test_assistant_unavailable_without_key(home, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    r = await home["client"].post("/api/assistant/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 503 and r.json()["error"]["code"] == "ai_unavailable"


async def test_assistant_tool_loop(home, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
    monkeypatch.setattr(settings, "anthropic_base_url", "https://anthropic.test")
    dev = home["device"]

    def handler(body, n):
        if n == 1:
            return httpx.Response(200, json={"stop_reason": "tool_use", "content": [
                {"type": "text", "text": "let me look"},
                {"type": "tool_use", "id": "tu_1", "name": "get_live_status", "input": {}},
                {"type": "tool_use", "id": "tu_2", "name": "get_today_summary", "input": {"device_id": dev["id"]}}]})
        return httpx.Response(200, json={"stop_reason": "end_turn", "content": [{"type": "text", "text": "البطارية بخير"}]})
    calls = _anthropic(handler, monkeypatch)
    r = await home["client"].post("/api/assistant/chat", json={"messages": [
        {"role": "user", "content": "شو وضع البطارية؟"}], "device_id": dev["id"]})
    assert r.status_code == 200, r.text
    assert r.json() == {"reply": "البطارية بخير", "used_tools": ["get_live_status", "get_today_summary"]}
    first, second = calls[0], calls[1]
    assert first["url"] == "https://anthropic.test/v1/messages" and first["headers"]["x-api-key"] == "sk-test"
    assert first["headers"]["anthropic-version"] == "2023-06-01"
    assert first["body"]["model"] == "claude-sonnet-5-5"
    assert {t["name"] for t in first["body"]["tools"]} == {"get_live_status", "get_today_summary", "get_history_summary", "list_recent_alerts", "get_settings"}
    assert "Arabic" in first["body"]["system"] and "ONLY data returned by your tools" in first["body"]["system"]  # grounded, Arabic default
    # second request carries the assistant tool_use turn and both tool results with real data
    msgs = second["body"]["messages"]
    assert msgs[-2]["role"] == "assistant" and msgs[-1]["role"] == "user"
    results = msgs[-1]["content"]
    assert [x["tool_use_id"] for x in results] == ["tu_1", "tu_2"]
    live = json.loads(results[0]["content"])
    assert live["device"] == "Demo" and "battery_soc" in live["metrics"]
    assert "pv_kwh" in json.loads(results[1]["content"])


async def test_assistant_tool_loop_is_capped_and_cannot_write(home, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")

    def handler(body, n):
        if body.get("tool_choice") == {"type": "none"}:
            return httpx.Response(200, json={"stop_reason": "end_turn", "content": [{"type": "text", "text": "done"}]})
        return httpx.Response(200, json={"stop_reason": "tool_use", "content": [
            {"type": "tool_use", "id": f"t{n}", "name": "change_setting", "input": {"key": "buzzer", "value": False}}]})
    calls = _anthropic(handler, monkeypatch)
    r = await home["client"].post("/api/assistant/chat", json={"messages": [{"role": "user", "content": "silence it"}]})
    assert r.status_code == 200 and r.json()["reply"] == "done"
    assert len(calls) == 6  # 5 tool rounds + the final no-tools answer
    # an unknown/write tool is never executed
    tool_result = calls[1]["body"]["messages"][-1]["content"][0]["content"]
    assert "unknown tool" in tool_result
    dev_id = home["device"]["id"]
    cmds = (await home["client"].get(f"/api/devices/{dev_id}/commands")).json()
    assert cmds["total"] == 0


async def test_assistant_validation_and_provider_errors(home, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
    c = home["client"]
    assert (await c.post("/api/assistant/chat", json={"messages": []})).status_code == 422
    assert (await c.post("/api/assistant/chat", json={"messages": [{"role": "assistant", "content": "x"}]})).status_code == 422
    calls = _anthropic(lambda body, n: httpx.Response(529, json={"error": "overloaded"}), monkeypatch)
    r = await c.post("/api/assistant/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 502 and r.json()["error"]["code"] == "ai_error"
    assert (await c.post("/api/assistant/chat", json={"messages": [{"role": "user", "content": "hi"}], "device_id": "00000000-0000-0000-0000-000000000000"})).status_code == 404
