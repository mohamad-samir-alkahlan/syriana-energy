"""Tenant isolation (cross-tenant => 404) and plan limits/features."""
import uuid
from datetime import timedelta

import pytest

from app import clock
from app.db import SessionLocal
from app.worker import expire_plans
from tests.conftest import add_demo_device, dt, make_client, register, set_plan


async def two_tenants():
    a, b = make_client(), make_client()
    ma = await register(a, "a@example.com", tenant_name="A")
    mb = await register(b, "b@example.com", tenant_name="B")
    await set_plan(ma["tenant"]["id"], "installer", type_="installer")
    await set_plan(mb["tenant"]["id"], "installer", type_="installer")
    return a, b, ma, mb


async def test_cross_tenant_access_is_404_everywhere():
    a, b, ma, mb = await two_tenants()
    dev = await add_demo_device(a, "A device")
    site = (await a.get("/api/sites")).json()[0]
    rule = (await a.get("/api/alert-rules")).json()[0]
    auto = (await a.post("/api/automations", json={"name": "x", "device_id": dev["id"],
            "conditions": [{"metric": "battery_soc", "op": "<", "value": 20}], "actions": [{"type": "notify", "message": "hi"}]})).json()
    key = (await a.post("/api/api-keys", json={"name": "k"})).json()
    cust = (await a.post("/api/customers", json={"name": "C", "owner_email": "c@example.com", "owner_name": "C"})).json()
    await a.post(f"/api/devices/{dev['id']}/settings", json={"key": "buzzer", "value": False, "confirm": True})
    alerts = (await a.get("/api/alerts")).json()
    # make an alert exist for A
    from app.models import Alert
    async with SessionLocal() as s:
        al = Alert(tenant_id=uuid.UUID(ma["tenant"]["id"]), type="x", title="t", title_ar="t")
        s.add(al)
        await s.commit()
        alert_id = str(al.id)

    d = dev["id"]
    gets = [f"/api/devices/{d}", f"/api/devices/{d}/live", f"/api/devices/{d}/history", f"/api/devices/{d}/energy",
            f"/api/devices/{d}/today", f"/api/devices/{d}/settings", f"/api/devices/{d}/commands",
            f"/api/automations/{auto['id']}"]
    for url in gets:
        assert (await a.get(url)).status_code == 200, url
        r = await b.get(url)
        assert r.status_code == 404, (url, r.text)
        assert r.json()["error"]["code"] == "not_found"
    assert (await b.patch(f"/api/devices/{d}", json={"name": "hacked"})).status_code == 404
    assert (await b.delete(f"/api/devices/{d}")).status_code == 404
    assert (await b.post(f"/api/devices/{d}/settings", json={"key": "buzzer", "value": False, "confirm": True})).status_code == 404
    assert (await b.patch(f"/api/sites/{site['id']}", json={"name": "x"})).status_code == 404
    assert (await b.delete(f"/api/sites/{site['id']}")).status_code == 404
    assert (await b.patch(f"/api/alert-rules/{rule['id']}", json={"enabled": False})).status_code == 404
    assert (await b.delete(f"/api/alert-rules/{rule['id']}")).status_code == 404
    assert (await b.patch(f"/api/automations/{auto['id']}", json={"enabled": False})).status_code == 404
    assert (await b.delete(f"/api/automations/{auto['id']}")).status_code == 404
    assert (await b.post(f"/api/alerts/{alert_id}/read")).status_code == 404
    assert (await b.delete(f"/api/api-keys/{key['id']}")).status_code == 404
    assert (await b.delete(f"/api/customers/{cust['id']}")).status_code == 404
    assert (await b.post("/api/auth/switch-tenant", json={"tenant_id": ma["tenant"]["id"]})).status_code == 404
    # B cannot attach a device to A's site
    r = await b.post("/api/devices", json={"site_id": site["id"], "driver": "demo", "credentials": {}, "external_id": "z", "name": "z"})
    assert r.status_code == 404
    # lists never leak
    assert (await b.get("/api/devices")).json() == []
    assert all(s["devices"] == [] for s in (await b.get("/api/sites")).json())
    assert (await b.get("/api/alerts")).json()["total"] == 0
    assert (await b.get("/api/automations")).json() == []
    assert (await b.get("/api/api-keys")).json() == []
    # A's data is untouched
    assert (await a.get(f"/api/devices/{d}")).json()["name"] == "A device"
    # invalid ids are also just 404
    assert (await a.get("/api/devices/not-a-uuid")).status_code == 404
    assert (await a.get(f"/api/devices/{uuid.uuid4()}")).status_code == 404
    await a.aclose(); await b.aclose()


async def test_installer_can_switch_into_own_customer_only():
    a, b, ma, mb = await two_tenants()
    r = await a.post("/api/customers", json={"name": "Cust1", "owner_email": "cust1@example.com", "owner_name": "Cust One"})
    assert r.status_code == 201
    cust = r.json()
    assert cust["initial_password"] and cust["devices"] == 0
    me = (await a.post("/api/auth/switch-tenant", json={"tenant_id": cust["id"]})).json()
    assert me["tenant"]["id"] == cust["id"] and me["role"] == "admin" and me["tenant"]["parent_id"] == ma["tenant"]["id"]
    assert {t["id"] for t in me["tenants"]} >= {ma["tenant"]["id"], cust["id"]}
    # customer data stays separate from the installer's
    d = await add_demo_device(a, "in customer")
    assert (await a.get("/api/auth/me")).json()["tenant"]["id"] == cust["id"]
    await a.post("/api/auth/switch-tenant", json={"tenant_id": ma["tenant"]["id"]})
    assert (await a.get(f"/api/devices/{d['id']}")).status_code == 404
    items = (await a.get("/api/customers")).json()["items"]
    assert items[0]["devices"] == 1 and items[0]["name"] == "Cust1"
    # B (another installer-less tenant) cannot jump into A's customer
    assert (await b.post("/api/auth/switch-tenant", json={"tenant_id": cust["id"]})).status_code == 404
    # the customer owner logs in directly and sees only their tenant
    c = make_client()
    r = await c.post("/api/auth/login", json={"email": "cust1@example.com", "password": cust["initial_password"]})
    assert r.status_code == 200 and r.json()["tenant"]["id"] == cust["id"]
    assert (await c.get("/api/customers")).status_code == 403  # no customers feature for a customer tenant
    assert (await c.get(f"/api/devices/{d['id']}")).status_code == 200
    await a.aclose(); await b.aclose(); await c.aclose()


async def test_free_plan_limits_and_features(client):
    me = await register(client)
    assert me["tenant"]["plan"]["code"] == "free"
    await add_demo_device(client, "one")
    sites = (await client.get("/api/sites")).json()
    r = await client.post("/api/devices", json={"site_id": sites[0]["id"], "driver": "demo", "credentials": {}, "external_id": "two", "name": "two"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "plan_limit"
    assert (await client.get("/api/tenant/usage")).json() == {"devices": 1, "max_devices": 1, "history_days": 7}
    for method, url, body in [("post", "/api/automations", {"name": "x", "conditions": [{"metric": "battery_soc", "op": "<", "value": 1}]}),
                              ("get", "/api/automations", None), ("post", "/api/api-keys", {"name": "k"}),
                              ("post", "/api/assistant/chat", {"messages": [{"role": "user", "content": "hi"}]}),
                              ("patch", "/api/tenant/branding", {"name": "X"}), ("get", "/api/customers", None),
                              ("patch", "/api/channels", {"email": {"enabled": True, "address": "a@b.co"}}),
                              ("patch", "/api/channels", {"webhook": {"enabled": True, "url": "https://example.org/h"}})]:
        r = await getattr(client, method)(url, **({"json": body} if body is not None else {}))
        assert r.status_code == 403 and r.json()["error"]["code"] == "feature_not_in_plan", (url, r.text)
    # a rule cannot route to email on the free plan
    rid = (await client.get("/api/alert-rules")).json()[0]["id"]
    r = await client.patch(f"/api/alert-rules/{rid}", json={"channels": ["inapp", "email"]})
    assert r.status_code == 403
    # telegram + inapp are fine for free
    assert (await client.patch(f"/api/alert-rules/{rid}", json={"channels": ["telegram"]})).status_code == 200


async def test_paid_plans_unlock_and_limits(client):
    me = await register(client)
    await set_plan(me["tenant"]["id"], "home")
    for i in range(3):
        await add_demo_device(client, f"d{i}")
    sites = (await client.get("/api/sites")).json()
    r = await client.post("/api/devices", json={"site_id": sites[0]["id"], "driver": "demo", "credentials": {}, "external_id": "x4", "name": "x4"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "plan_limit" and r.json()["error"]["max_devices"] == 3
    assert (await client.post("/api/api-keys", json={"name": "k"})).status_code == 201
    plan = (await client.get("/api/tenant")).json()["plan"]
    assert plan["max_devices"] == 3 and plan["history_days"] == 365 and set(plan["features"]) == {"control", "ai", "email", "webhook", "automations", "api"}
    assert (await client.patch("/api/tenant/branding", json={"name": "X"})).status_code == 403  # white_label is installer-only
    await set_plan(me["tenant"]["id"], "pro")
    assert (await client.get("/api/tenant/usage")).json()["max_devices"] == 10


async def test_public_plans_seeded(client):
    plans = {p["code"]: p for p in (await client.get("/api/public/plans")).json()}
    assert list(plans) == ["free", "home", "pro", "installer"]
    assert (plans["free"]["max_devices"], plans["free"]["history_days"], plans["free"]["features"]) == (1, 7, [])
    assert (plans["home"]["price_month"], plans["home"]["price_year"], plans["home"]["max_devices"], plans["home"]["history_days"]) == (4, 40, 3, 365)
    assert (plans["pro"]["price_month"], plans["pro"]["max_devices"], plans["pro"]["history_days"]) == (9, 10, 730)
    assert plans["pro"]["features"] == plans["home"]["features"]
    assert plans["installer"]["price_month"] == 2 and plans["installer"]["max_devices"] == 500
    assert {"white_label", "customers"} <= set(plans["installer"]["features"]) and plans["installer"]["currency"] == "USD"


async def test_plan_expiry_downgrades_to_free(client):
    me = await register(client)
    tid = me["tenant"]["id"]
    clock.set_now(dt(2026, 10, 22, 12, 0))
    await set_plan(tid, "home", expires=dt(2026, 10, 22, 11, 0))  # already expired
    # even before the worker runs, features are not granted
    r = await client.post("/api/api-keys", json={"name": "k"})
    assert r.status_code == 403
    async with SessionLocal() as s:
        n = await expire_plans(s, clock.utcnow())
        await s.commit()
    assert n == 1
    t = (await client.get("/api/tenant")).json()
    assert t["plan"]["code"] == "free" and t["plan_expires_at"] is None
    alerts = (await client.get("/api/alerts")).json()["items"]
    assert alerts[0]["type"] == "plan_expired"
    await set_plan(tid, "home", expires=dt(2026, 10, 25, 0, 0))
    assert (await client.post("/api/api-keys", json={"name": "k"})).status_code == 201


async def test_installer_family_device_limit_and_child_features():
    a, b, ma, mb = await two_tenants()
    cust = (await a.post("/api/customers", json={"name": "C", "owner_email": "cc@example.com", "owner_name": "C", "password": "custpass123"})).json()
    assert "initial_password" not in cust
    await a.post("/api/auth/switch-tenant", json={"tenant_id": cust["id"]})
    t = (await a.get("/api/tenant")).json()
    assert t["plan"]["code"] == "installer" and "customers" not in t["plan"]["features"]
    assert (await a.get("/api/customers")).status_code == 403  # child tenants cannot have customers
    # shared max_devices counts the whole family
    from app.db import SessionLocal as SL
    from app.models import Plan
    async with SL() as s:
        p = await s.get(Plan, "installer")
        p.max_devices = 2
        await s.commit()
    await add_demo_device(a, "c1")
    await a.post("/api/auth/switch-tenant", json={"tenant_id": ma["tenant"]["id"]})
    await add_demo_device(a, "own1")
    sites = (await a.get("/api/sites")).json()
    r = await a.post("/api/devices", json={"site_id": sites[0]["id"], "driver": "demo", "credentials": {}, "external_id": "own2", "name": "x"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "plan_limit"
    await a.aclose(); await b.aclose()


async def test_white_label_branding_resolution(client):
    me = await register(client, "inst@example.com")
    tid = me["tenant"]["id"]
    await set_plan(tid, "installer", type_="installer")
    r = await client.patch("/api/tenant/branding", json={"name": "SolarCo", "name_ar": "سولار كو", "primary_color": "#112233",
                                                          "accent_color": "#445566", "support_email": "help@solarco.example.com",
                                                          "logo_url": "https://cdn.test/logo.png", "custom_domain": "energy.solarco.test"})
    assert r.status_code == 200
    b = r.json()["branding"]
    assert b["name"] == "SolarCo" and b["primary_color"] == "#112233" and b["powered_by"] is False
    # public resolution by host / custom domain
    pub = (await client.get("/api/public/branding?host=energy.solarco.test")).json()
    assert pub["name"] == "SolarCo" and pub["logo_url"] == "https://cdn.test/logo.png"
    pub = (await client.get("/api/public/branding?host=Energy.SolarCo.test:443")).json()
    assert pub["name"] == "SolarCo"
    default = (await client.get("/api/public/branding?host=unknown.example.com")).json()
    assert default["name"] == "Syriana Energy" and default["primary_color"] == "#DA7756" and default["powered_by"] is True
    # child inherits the parent's branding unless it has its own
    cust = (await client.post("/api/customers", json={"name": "Cust", "owner_email": "ce@example.com", "owner_name": "CE"})).json()
    await client.post("/api/auth/switch-tenant", json={"tenant_id": cust["id"]})
    t = (await client.get("/api/tenant")).json()
    assert t["branding"]["name"] == "SolarCo" and t["branding"]["powered_by"] is False
    r = await client.patch("/api/tenant/branding", json={"name": "Cust Own", "primary_color": "#ABCDEF"})
    assert r.status_code == 200 and r.json()["branding"]["name"] == "Cust Own"
    await client.post("/api/auth/switch-tenant", json={"tenant_id": tid})
    assert (await client.get("/api/tenant")).json()["branding"]["name"] == "SolarCo"
    # validation
    assert (await client.patch("/api/tenant/branding", json={"primary_color": "red"})).status_code == 422
    assert (await client.patch("/api/tenant/branding", json={"custom_domain": "not a domain"})).status_code == 422
    other = make_client()
    m2 = await register(other, "inst2@example.com")
    await set_plan(m2["tenant"]["id"], "installer", type_="installer")
    r = await other.patch("/api/tenant/branding", json={"custom_domain": "energy.solarco.test"})
    assert r.status_code == 409
    await other.aclose()


async def test_team_management(client):
    me = await register(client, "owner@example.com")
    r = await client.post("/api/users", json={"email": "adm@example.com", "name": "Adm", "role": "admin", "password": "adminpass1"})
    assert r.status_code == 201
    uid = r.json()["id"]
    users = (await client.get("/api/users")).json()
    assert {u["email"] for u in users} == {"owner@example.com", "adm@example.com"}
    assert (await client.post("/api/users", json={"email": "adm@example.com", "name": "x", "role": "viewer", "password": "xxxxxxxx"})).status_code == 409
    # last owner protection
    owner_id = me["user"]["id"]
    assert (await client.patch(f"/api/users/{owner_id}", json={"role": "viewer"})).status_code == 409
    assert (await client.delete(f"/api/users/{owner_id}")).status_code == 400  # cannot remove yourself
    assert (await client.patch(f"/api/users/{uid}", json={"role": "viewer"})).json()["role"] == "viewer"
    # admins cannot mint owners
    a = make_client()
    await a.post("/api/auth/login", json={"email": "adm@example.com", "password": "adminpass1"})
    await client.patch(f"/api/users/{uid}", json={"role": "admin"})
    r = await a.post("/api/users", json={"email": "o2@example.com", "name": "O2", "role": "owner", "password": "ownerpass1"})
    assert r.status_code == 403
    assert (await client.delete(f"/api/users/{uid}")).status_code == 204
    assert (await a.get("/api/auth/me")).status_code == 401  # removed users lose access (no membership / user deleted)
    await a.aclose()
