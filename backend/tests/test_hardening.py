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


def _link_token(fake, to: str) -> str:
    body = [b for (t, _, b) in fake.emails if t == to][-1]
    return body.split("token=")[1].split()[0]


async def test_password_reset_flow(client, clean):
    await register(client, "reset@example.com")
    other = make_client()
    assert (await other.post("/api/auth/login", json={"email": "reset@example.com", "password": "password123"})).status_code == 200
    anon = make_client()
    assert (await anon.post("/api/auth/password/forgot", json={"email": "nobody@example.com"})).status_code == 204
    assert (await anon.post("/api/auth/password/forgot", json={"email": "reset@example.com", "locale": "en"})).status_code == 204
    token = _link_token(clean, "reset@example.com")
    assert "/en/reset-password?token=" in [b for (t, _, b) in clean.emails if t == "reset@example.com"][-1]
    assert (await anon.post("/api/auth/password/reset", json={"token": "junk", "password": "newpassword1"})).status_code == 400
    assert (await anon.post("/api/auth/password/reset", json={"token": token, "password": "newpassword1"})).status_code == 204
    # single use: the token is bound to the old password hash
    assert (await anon.post("/api/auth/password/reset", json={"token": token, "password": "another-pass"})).status_code == 400
    assert (await other.get("/api/auth/me")).status_code == 401  # every session was revoked
    r = await anon.post("/api/auth/login", json={"email": "reset@example.com", "password": "newpassword1"})
    assert r.status_code == 200 and r.json()["user"]["email_verified"] is True


async def test_email_verification_and_odoo_match(client, clean):
    me = await register(client, "verify@example.com")
    assert me["user"]["email_verified"] is False
    token = _link_token(clean, "verify@example.com")
    h = {"X-Odoo-Secret": "odoo-test-secret"}
    hook = {"email": "verify@example.com", "plan_code": "home", "expires_at": "2027-01-01T00:00:00Z", "invoice_ref": "INV/V/1"}
    r = await client.post("/api/billing/odoo/webhook", json=hook, headers=h)
    assert r.status_code == 404  # an unverified e-mail never receives someone's payment
    assert (await client.post("/api/auth/verify-email", json={"token": token})).status_code == 204
    assert (await client.get("/api/auth/me")).json()["user"]["email_verified"] is True
    r = await client.post("/api/billing/odoo/webhook", json=hook, headers=h)
    assert r.status_code == 200, r.text
    # a reset token is not a verify token
    assert (await client.post("/api/auth/verify-email", json={"token": "x.y.z"})).status_code == 400


async def test_login_skips_suspended_first_tenant(client):
    me = await register(client, "multi@example.com")
    first = me["tenant"]["id"]
    async with SessionLocal() as s:
        from app.models import Membership, User
        from sqlalchemy import select
        u = (await s.execute(select(User).where(User.email == "multi@example.com"))).scalar_one()
        t2 = Tenant(name="Second", type="home", plan_code="free")
        s.add(t2)
        await s.flush()
        s.add(Membership(user_id=u.id, tenant_id=t2.id, role="owner"))
        (await s.get(Tenant, uuid.UUID(first))).suspended = True
        await s.commit()
        second = str(t2.id)
    c = make_client()
    r = await c.post("/api/auth/login", json={"email": "multi@example.com", "password": "password123"})
    assert r.status_code == 200 and r.json()["tenant"]["id"] == second
    assert (await c.get("/api/auth/me")).status_code == 200


async def test_api_keys_revoked_with_member(client):
    me = await register(client)
    await set_plan(me["tenant"]["id"], "home")
    r = await client.post("/api/users", json={"email": f"k-{uuid.uuid4().hex[:6]}@example.com", "name": "K",
                                              "role": "admin", "password": "password123"})
    uid, email = r.json()["id"], r.json()["email"]
    m = make_client()
    await m.post("/api/auth/login", json={"email": email, "password": "password123"})
    key = (await m.post("/api/api-keys", json={"name": "theirs"})).json()["key"]
    h = {"Authorization": f"Bearer {key}"}
    assert (await make_client().get("/api/devices", headers=h)).status_code == 200
    assert (await client.patch(f"/api/users/{uid}", json={"role": "viewer"})).status_code == 200
    assert (await make_client().get("/api/devices", headers=h)).status_code == 401
