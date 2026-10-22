import ipaddress
import uuid

import httpx

from app.config import settings
from app.db import SessionLocal
from app.models import Tenant
from app.services import notify, polling
from tests.conftest import add_demo_device, make_client, register, set_plan


async def test_custom_domain_cannot_claim_platform_host(client, monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://energy.syriana.dev")
    monkeypatch.setattr(settings, "reserved_domains", "syriana.energy")
    me = await register(client)
    await set_plan(me["tenant"]["id"], "installer", type_="installer")
    for dom in ("energy.syriana.dev", "x.energy.syriana.dev", "syriana.energy", "app.syriana.energy"):
        r = await client.patch("/api/tenant/branding", json={"custom_domain": dom})
        assert r.status_code == 422, dom
    assert (await client.patch("/api/tenant/branding", json={"custom_domain": "solar.example.com"})).status_code == 200


async def test_telegram_unlink(client):
    me = await register(client)
    async with SessionLocal() as s:
        t = await s.get(Tenant, uuid.UUID(me["tenant"]["id"]))
        t.telegram_chats = [{"chat_id": 111, "title": "Ali"}, {"chat_id": -222, "title": "Group"}]
        await s.commit()
    chats = (await client.get("/api/channels")).json()["telegram"]["chats"]
    assert [c["id"] for c in chats] == ["111", "-222"]
    r = await client.delete("/api/channels/telegram/111")
    assert r.status_code == 200 and [c["id"] for c in r.json()["telegram"]["chats"]] == ["-222"]
    assert (await client.delete("/api/channels/telegram/111")).status_code == 404


async def test_viewer_does_not_see_webhook_or_http_action_secrets(client, monkeypatch):
    monkeypatch.setattr(settings, "allow_private_urls", True)
    me = await register(client)
    await set_plan(me["tenant"]["id"], "home")
    dev = await add_demo_device(client)
    hook = "https://hooks.example.com/secret-token"
    assert (await client.patch("/api/channels", json={"webhook": {"url": hook, "enabled": True}})).status_code == 200
    r = await client.post("/api/automations", json={
        "name": "a", "device_id": dev["id"],
        "conditions": [{"metric": "battery_soc", "op": "<", "value": 20}],
        "actions": [{"type": "http", "method": "POST", "url": hook, "body": {"k": "secret"}}]})
    assert r.status_code == 201, r.text
    r = await client.post("/api/users", json={"email": f"v-{uuid.uuid4().hex[:6]}@example.com", "name": "V",
                                              "role": "viewer", "password": "password123"})
    assert r.status_code == 201
    v = make_client()
    assert (await v.post("/api/auth/login", json={"email": r.json()["email"], "password": "password123"})).status_code == 200
    assert (await v.get("/api/channels")).json()["webhook"]["url"] is None
    act = (await v.get("/api/automations")).json()[0]["actions"][0]
    assert act["type"] == "http" and "url" not in act and "body" not in act
    assert (await client.get("/api/channels")).json()["webhook"]["url"] == hook


async def test_suspended_tenants_are_not_polled(client):
    me = await register(client)
    dev = await add_demo_device(client)
    async with SessionLocal() as s:
        assert uuid.UUID(dev["id"]) in [d for d, _ in await polling.due_devices(s)]
        t = await s.get(Tenant, uuid.UUID(me["tenant"]["id"]))
        t.suspended = True
        await s.commit()
    async with SessionLocal() as s:
        assert uuid.UUID(dev["id"]) not in [d for d, _ in await polling.due_devices(s)]


async def test_assistant_rate_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
    monkeypatch.setattr(settings, "assistant_hourly_limit", 0)
    me = await register(client)
    await set_plan(me["tenant"]["id"], "home")
    r = await client.post("/api/assistant/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 429


async def test_safe_request_connects_to_checked_ip(monkeypatch):
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(host=req.url.host, header=req.headers["host"], sni=req.extensions.get("sni_hostname"))
        return httpx.Response(200)

    async def fake_ips(url):
        return [ipaddress.ip_address("93.184.216.34")]

    real = httpx.AsyncClient
    monkeypatch.setattr(notify, "_safe_ips", fake_ips)
    monkeypatch.setattr(notify.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    r = await notify.safe_request("POST", "https://hooks.example.com:8443/x?y=1", 5, json={})
    assert r.status_code == 200
    assert seen == {"host": "93.184.216.34", "header": "hooks.example.com:8443", "sni": "hooks.example.com"}

    async def no_ips(url):
        return None
    monkeypatch.setattr(notify, "_safe_ips", no_ips)
    try:
        await notify.safe_request("GET", "http://rebind.example.com/", 5)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
