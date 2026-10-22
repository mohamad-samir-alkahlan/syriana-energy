import uuid
from datetime import timedelta

from sqlalchemy import select

from app import clock
from app.db import SessionLocal
from app.models import Alert, Tenant, TelegramLinkCode
from app.services import telegram as tg
from app.services.notify import is_safe_url
from app.worker import expire_plans
from tests.conftest import add_demo_device, dt, make_client, make_superadmin, register, set_plan


# ------------------------------------------------------------------ telegram
async def update(db, chat_id, text, title="Mohamad", chat_type="private"):
    await tg.handle_update(db, {"update_id": 1, "message": {"text": text, "chat": {"id": chat_id, "type": chat_type, "first_name": title}}})
    await db.commit()


async def test_link_code_flow_multiple_chats(client, fake):
    me = await register(client, locale="ar")
    r = await client.post("/api/channels/telegram/link")
    assert r.status_code == 200
    j = r.json()
    assert len(j["code"]) == 6 and j["bot_username"] == "TestBot" and j["deep_link"] == f"https://t.me/TestBot?start={j['code']}"
    assert (await client.get("/api/channels")).json()["telegram"] == {"linked": False, "chat_title": None, "chats": []}

    async with SessionLocal() as db:
        await update(db, 1001, f"/start {j['code']}", title="Mohamad")
    assert "ربط" in fake.telegram_msgs[-1][1] and "linked" in fake.telegram_msgs[-1][1].lower()  # Arabic + English
    ch = (await client.get("/api/channels")).json()["telegram"]
    assert ch["linked"] is True and ch["chat_title"] == "Mohamad"
    # a code is single-use
    async with SessionLocal() as db:
        await update(db, 1002, f"/start {j['code']}")
    assert "غير صالح" in fake.telegram_msgs[-1][1]
    # second chat with a fresh code
    j2 = (await client.post("/api/channels/telegram/link")).json()
    async with SessionLocal() as db:
        await update(db, 1002, f"/start {j2['code'].lower()}", title="Family group")  # case-insensitive
    ch = (await client.get("/api/channels")).json()["telegram"]
    assert len(ch["chats"]) == 2 and "Family group" in ch["chat_title"]
    # linking the same chat again does not duplicate
    j3 = (await client.post("/api/channels/telegram/link")).json()
    async with SessionLocal() as db:
        await update(db, 1002, f"/start {j3['code']}")
    assert len((await client.get("/api/channels")).json()["telegram"]["chats"]) == 2


async def test_expired_code_rejected(client, fake):
    await register(client)
    j = (await client.post("/api/channels/telegram/link")).json()
    async with SessionLocal() as db:
        row = await db.get(TelegramLinkCode, j["code"])
        row.expires_at = clock.utcnow() - timedelta(minutes=1)
        await db.commit()
        await update(db, 1, f"/start {j['code']}")
    assert "غير صالح" in fake.telegram_msgs[-1][1]
    assert (await client.get("/api/channels")).json()["telegram"]["linked"] is False


async def test_code_ttl_is_15_minutes(client):
    await register(client)
    j = (await client.post("/api/channels/telegram/link")).json()
    async with SessionLocal() as db:
        row = await db.get(TelegramLinkCode, j["code"])
        mins = (row.expires_at - clock.utcnow()).total_seconds() / 60
    assert 14 < mins <= 15


async def test_status_command_in_user_language(client, fake):
    me = await register(client, locale="en")
    dev = await add_demo_device(client, "Roof Inverter")
    j = (await client.post("/api/channels/telegram/link")).json()
    async with SessionLocal() as db:
        await update(db, 77, f"/start {j['code']}")
        await update(db, 77, "/status")
    txt = fake.telegram_msgs[-1][1]
    assert "Roof Inverter" in txt and "Battery:" in txt and "online" in txt
    async with SessionLocal() as db:
        await update(db, 999, "/status")  # unlinked chat
    assert "not linked" in fake.telegram_msgs[-1][1].lower() or "غير مربوطة" in fake.telegram_msgs[-1][1]
    # arabic owner
    c2 = make_client()
    await register(c2, locale="ar")
    await add_demo_device(c2, "المولدة")
    j = (await c2.post("/api/channels/telegram/link")).json()
    async with SessionLocal() as db:
        await update(db, 88, f"/start {j['code']}")
        await update(db, 88, "/status")
    assert "المولدة" in fake.telegram_msgs[-1][1] and "البطارية" in fake.telegram_msgs[-1][1]
    await c2.aclose()


async def test_webhook_endpoint_secret_and_handling(client, fake):
    await register(client)
    j = (await client.post("/api/channels/telegram/link")).json()
    body = {"update_id": 5, "message": {"text": f"/start {j['code']}", "chat": {"id": 4242, "type": "private", "first_name": "X"}}}
    assert (await client.post("/api/telegram/webhook/wrong", json=body)).status_code == 404
    assert (await client.post("/api/telegram/webhook/whsec-test", json=body)).status_code == 200
    assert (await client.get("/api/channels")).json()["telegram"]["linked"] is True
    # unknown / malformed updates are ignored politely
    assert (await client.post("/api/telegram/webhook/whsec-test", json={"update_id": 6})).status_code == 200


async def test_channel_test_endpoint(client, fake):
    await register(client)
    assert (await client.post("/api/channels/test", json={"channel": "telegram"})).status_code == 400
    j = (await client.post("/api/channels/telegram/link")).json()
    async with SessionLocal() as db:
        await update(db, 9, f"/start {j['code']}")
    n = len(fake.telegram_msgs)
    r = await client.post("/api/channels/test", json={"channel": "telegram"})
    assert r.status_code == 200 and r.json()["ok"] is True and len(fake.telegram_msgs) == n + 1
    assert (await client.post("/api/channels/test", json={"channel": "inapp"})).json()["ok"] is True
    assert (await client.get("/api/alerts")).json()["items"][0]["type"] == "test"
    assert (await client.post("/api/channels/test", json={"channel": "email"})).status_code == 400


# ------------------------------------------------------------------ billing
async def test_odoo_webhook_activate_renew_idempotent(client, clean):
    me = await register(client, "payer@example.com")
    tid = me["tenant"]["id"]
    h = {"X-Odoo-Secret": "odoo-test-secret"}
    body = {"tenant_id": tid, "plan_code": "home", "expires_at": "2026-11-22T00:00:00Z", "invoice_ref": "INV/2026/0001"}
    assert (await client.post("/api/billing/odoo/webhook", json=body)).status_code == 401
    assert (await client.post("/api/billing/odoo/webhook", json=body, headers={"X-Odoo-Secret": "nope"})).status_code == 401
    r = await client.post("/api/billing/odoo/webhook", json=body, headers=h)
    assert r.status_code == 200 and r.json()["plan_code"] == "home"
    t = (await client.get("/api/tenant")).json()
    assert t["plan"]["code"] == "home" and t["plan_expires_at"].startswith("2026-11-22")
    # duplicate invoice => no-op
    r = await client.post("/api/billing/odoo/webhook", json={**body, "plan_code": "pro"}, headers=h)
    assert r.json() == {"ok": True, "duplicate": True}
    assert (await client.get("/api/tenant")).json()["plan"]["code"] == "home"
    # renewal by e-mail (only once the address is verified) with a new invoice and upgrade
    token = [b for (to, _, b) in clean.emails if to == "payer@example.com"][-1].split("token=")[1].split()[0]
    assert (await client.post("/api/auth/verify-email", json={"token": token})).status_code == 204
    r = await client.post("/api/billing/odoo/webhook", headers=h,
                          json={"email": "PAYER@example.com", "plan_code": "pro", "expires_at": "2027-01-01T00:00:00Z", "invoice_ref": "INV/2026/0002"})
    assert r.status_code == 200
    assert (await client.get("/api/tenant")).json()["plan"]["code"] == "pro"
    # validation
    assert (await client.post("/api/billing/odoo/webhook", headers=h, json={"tenant_id": tid, "plan_code": "gold"})).status_code == 422
    assert (await client.post("/api/billing/odoo/webhook", headers=h, json={"plan_code": "home"})).status_code == 422
    assert (await client.post("/api/billing/odoo/webhook", headers=h, json={"tenant_id": str(uuid.uuid4()), "plan_code": "home"})).status_code == 404
    assert (await client.post("/api/billing/odoo/webhook", headers=h, json={"email": "ghost@example.com", "plan_code": "home"})).status_code == 404


async def test_odoo_installer_plan_makes_tenant_installer_and_expiry_downgrades(client):
    me = await register(client, "inst@example.com")
    tid = me["tenant"]["id"]
    h = {"X-Odoo-Secret": "odoo-test-secret"}
    clock.set_now(dt(2026, 10, 22, 12, 0))
    await client.post("/api/billing/odoo/webhook", headers=h, json={"tenant_id": tid, "plan_code": "installer", "expires_at": "2026-10-24T00:00:00Z"})
    t = (await client.get("/api/tenant")).json()
    assert t["type"] == "installer" and "customers" in t["plan"]["features"]
    assert (await client.get("/api/customers")).status_code == 200
    clock.set_now(dt(2026, 10, 25, 0, 0))
    async with SessionLocal() as s:
        assert await expire_plans(s, clock.utcnow()) == 1
        await s.commit()
    assert (await client.get("/api/tenant")).json()["plan"]["code"] == "free"
    assert (await client.get("/api/customers")).status_code == 403


# ------------------------------------------------------------------ admin
async def test_admin_endpoints_require_superadmin(client):
    await register(client, "plain@example.com")
    for url in ("/api/admin/stats", "/api/admin/tenants", "/api/admin/plans"):
        r = await client.get(url)
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    assert (await client.patch("/api/admin/plans/free", json={"max_devices": 5})).status_code == 403


async def test_admin_stats_tenants_plans(client):
    other = make_client()
    mo = await register(other, "cust@example.com", tenant_name="Cust Home")
    await set_plan(mo["tenant"]["id"], "home")
    await add_demo_device(other)
    inst = make_client()
    mi = await register(inst, "inst@example.com", tenant_name="Solar Installer")
    await set_plan(mi["tenant"]["id"], "installer", type_="installer")
    for i in range(3):
        await add_demo_device(inst, f"i{i}")
    me = await register(client, "root@example.com", tenant_name="Root")
    await make_superadmin("root@example.com")

    s = (await client.get("/api/admin/stats")).json()
    assert s["tenants"] == 3 and s["users"] == 3 and s["devices"] == 4 and s["devices_online"] == 4
    assert s["by_plan"]["home"] == 1 and s["by_plan"]["installer"] == 1 and s["by_plan"]["free"] == 1 and s["by_plan"]["pro"] == 0
    assert len(s["signups_30d"]) == 30 and sum(n for _, n in s["signups_30d"]) == 3
    assert s["mrr_estimate"] == 4 + 2 * 3  # home $4 + installer $2 x 3 devices

    r = (await client.get("/api/admin/tenants")).json()
    assert r["total"] == 3 and {i["name"] for i in r["items"]} == {"Cust Home", "Solar Installer", "Root"}
    row = [i for i in r["items"] if i["name"] == "Solar Installer"][0]
    assert row["devices"] == 3 and row["users"] == 1 and row["plan"] == "installer" and row["suspended"] is False and row["type"] == "installer"
    assert [i["name"] for i in (await client.get("/api/admin/tenants?q=solar")).json()["items"]] == ["Solar Installer"]
    assert [i["name"] for i in (await client.get("/api/admin/tenants?q=cust@example")).json()["items"]] == ["Cust Home"]

    # change plan / suspend
    tid = mo["tenant"]["id"]
    r = await client.patch(f"/api/admin/tenants/{tid}", json={"plan_code": "pro", "plan_expires_at": "2027-01-01T00:00:00Z"})
    assert r.status_code == 200 and r.json()["plan"] == "pro"
    assert (await other.get("/api/tenant")).json()["plan"]["code"] == "pro"
    assert (await client.patch(f"/api/admin/tenants/{tid}", json={"plan_code": "gold"})).status_code == 422
    r = await client.patch(f"/api/admin/tenants/{tid}", json={"suspended": True})
    assert r.json()["suspended"] is True
    r = await other.get("/api/devices")
    assert r.status_code == 403 and r.json()["error"]["code"] == "tenant_suspended"
    await client.patch(f"/api/admin/tenants/{tid}", json={"suspended": False, "plan_expires_at": None})
    assert (await other.get("/api/devices")).status_code == 200
    r = await client.patch(f"/api/admin/tenants/{tid}", json={"type": "installer"})
    assert r.json()["type"] == "installer"
    # regression (found by the full-stack E2E): assigning the installer plan alone must make the tenant an installer,
    # otherwise /api/customers answers feature_not_in_plan even though the plan has the feature
    await client.patch(f"/api/admin/tenants/{tid}", json={"type": "home", "plan_code": "pro"})
    r = await client.patch(f"/api/admin/tenants/{tid}", json={"plan_code": "installer"})
    assert r.json()["type"] == "installer"
    assert (await other.get("/api/customers")).status_code == 200
    assert (await client.patch(f"/api/admin/tenants/{uuid.uuid4()}", json={"suspended": True})).status_code == 404

    # plans
    plans = (await client.get("/api/admin/plans")).json()
    assert [p["code"] for p in plans] == ["free", "home", "pro", "installer"]
    r = await client.patch("/api/admin/plans/home", json={"price_month": 5, "max_devices": 4, "features": ["control", "ai"]})
    assert r.status_code == 200 and r.json()["price_month"] == 5 and r.json()["max_devices"] == 4 and r.json()["features"] == ["control", "ai"]
    pub = {p["code"]: p for p in (await client.get("/api/public/plans")).json()}
    assert pub["home"]["max_devices"] == 4
    assert (await client.patch("/api/admin/plans/home", json={"features": ["teleport"]})).status_code == 422
    assert (await client.patch("/api/admin/plans/home", json={"max_devices": 0})).status_code == 422
    assert (await client.patch("/api/admin/plans/nope", json={"max_devices": 3})).status_code == 404
    await other.aclose(); await inst.aclose()


# ------------------------------------------------------------------ SSRF guard
async def test_is_safe_url():
    for bad in ("http://127.0.0.1/x", "http://localhost/x", "http://10.0.0.5/x", "http://192.168.1.1/", "http://169.254.169.254/latest",
                "http://[::1]/", "file:///etc/passwd", "ftp://8.8.8.8/", "http://router.local/", "not a url", "http://0.0.0.0/"):
        assert not await is_safe_url(bad), bad
    assert await is_safe_url("https://8.8.8.8/hook") and await is_safe_url("http://1.1.1.1:8080/x")


async def test_worker_long_polling_links_and_answers(client, fake, monkeypatch):
    """getUpdates loop: processes /start CODE and /status, persists the offset, stops on the stop event."""
    import asyncio
    import httpx
    from app.config import settings
    from app.models import KV
    monkeypatch.setattr(settings, "telegram_bot_token", "123:TESTTOKEN")
    me = await register(client, locale="en")
    await add_demo_device(client, "Poll Inverter")
    code = (await client.post("/api/channels/telegram/link")).json()["code"]
    stop = asyncio.Event()
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/bot123:TESTTOKEN/getUpdates"
        offset = int(req.url.params["offset"])
        seen.append(offset)
        if offset == 0:
            return httpx.Response(200, json={"ok": True, "result": [
                {"update_id": 41, "message": {"text": f"/start {code}", "chat": {"id": 555, "type": "private", "first_name": "Mo"}}},
                {"update_id": 42, "message": {"text": "/status", "chat": {"id": 555, "type": "private", "first_name": "Mo"}}}]})
        stop.set()
        return httpx.Response(200, json={"ok": True, "result": []})

    await asyncio.wait_for(tg.poll_forever(SessionLocal, stop, transport=httpx.MockTransport(handler)), 10)
    assert seen == [0, 43]
    assert (await client.get("/api/channels")).json()["telegram"]["chat_title"] == "Mo"
    texts = [m[1] for m in fake.telegram_msgs if m[0] == 555]
    assert len(texts) == 2 and "Poll Inverter" in texts[1]
    async with SessionLocal() as s:
        assert (await s.get(KV, "telegram_offset")).value == 43
