import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, text

from app import clock, cli
from app.db import SessionLocal
from app.drivers.registry import get_driver
from app.models import Alert, Device, Reading, User
from app.security import decrypt_json
from app.services import polling
from app.worker import maintenance_tick, poll_scheduler, purge_readings
from tests.conftest import add_demo_device, dt, make_client, register, set_plan
from tests.test_eybond import CREDS, EXT, FakeCloud


async def count_readings(did):
    async with SessionLocal() as s:
        return (await s.execute(text("SELECT count(*) FROM readings WHERE device_id=:d"), {"d": uuid.UUID(did)})).scalar_one()


async def test_poll_device_stores_reading_and_raises_grid_alerts(client, fake):
    me = await register(client, locale="en")
    await set_plan(me["tenant"]["id"], "pro")
    clock.set_now(dt(2026, 10, 22, 0, 30))  # grid is on (first 2h of the 6h cycle)
    dev = await add_demo_device(client)
    live = (await client.get(f"/api/devices/{dev['id']}/live")).json()
    assert live["online"] is True and live["metrics"]["grid_available"] is True and live["ts"].startswith("2026-10-22T00:30")
    assert await count_readings(dev["id"]) == 1
    clock.set_now(dt(2026, 10, 22, 2, 30))  # grid is off now
    async with SessionLocal() as s:
        res = await polling.poll_device(s, uuid.UUID(dev["id"]))
        await s.commit()
    assert [a["type"] for a in res["alerts"]] == ["grid_lost"]
    clock.set_now(dt(2026, 10, 22, 6, 30))  # next cycle's grid window (06:00-08:00)
    async with SessionLocal() as s:
        res = await polling.poll_device(s, uuid.UUID(dev["id"]))
        await s.commit()
    assert [a["type"] for a in res["alerts"]] == ["grid_restored"]
    types = [a["type"] for a in (await client.get("/api/alerts")).json()["items"]]
    assert types[:2] == ["grid_restored", "grid_lost"]
    # energy and outage show up in the aggregates
    today = (await client.get(f"/api/devices/{dev['id']}/today")).json()
    assert len(today["grid_outages"]) >= 1
    assert (await client.get(f"/api/devices/{dev['id']}/live")).json()["metrics"]["energy_pv_today"] >= 0


async def test_poll_failure_keeps_last_data_and_marks_offline(client):
    me = await register(client)
    clock.set_now(dt(2026, 10, 22, 12, 0))
    dev = await add_demo_device(client)
    drv = get_driver("demo")
    orig = drv.read

    async def boom(device):
        raise RuntimeError("kaboom")
    drv.read = boom
    try:
        clock.set_now(dt(2026, 10, 22, 12, 5))
        async with SessionLocal() as s:
            assert await polling.poll_device(s, uuid.UUID(dev["id"])) is None
            await s.commit()
    finally:
        drv.read = orig
    live = (await client.get(f"/api/devices/{dev['id']}/live")).json()
    assert live["online"] is False and live["metrics"]  # stale data kept, flagged offline (older than 3 x 15s)
    async with SessionLocal() as s:
        d = await s.get(Device, uuid.UUID(dev["id"]))
        assert "kaboom" in d.last_error


async def test_maintenance_tick_offline_alert_and_online_flags(client, fake):
    me = await register(client)
    clock.set_now(dt(2026, 10, 22, 12, 0))
    dev = await add_demo_device(client)
    r = await maintenance_tick(dt(2026, 10, 22, 12, 5))
    assert r["offline"] == 0
    r = await maintenance_tick(dt(2026, 10, 22, 12, 12))
    assert r["offline"] == 1
    assert (await client.get("/api/alerts")).json()["items"][0]["type"] == "device_offline"
    async with SessionLocal() as s:
        d = await s.get(Device, uuid.UUID(dev["id"]))
        assert d.online is False


async def test_scheduler_polls_devices(client):
    me = await register(client)
    dev = await add_demo_device(client)
    before = await count_readings(dev["id"])
    stop = asyncio.Event()
    task = asyncio.create_task(poll_scheduler(stop))
    await asyncio.sleep(2.2)
    stop.set()
    await asyncio.wait_for(task, 5)
    await asyncio.sleep(0.3)
    assert await count_readings(dev["id"]) > before


async def test_retention_purge_follows_plan(client):
    free = await register(client)
    fdev = await add_demo_device(client, "free dev")
    other = make_client()
    pro = await register(other)
    await set_plan(pro["tenant"]["id"], "home")
    pdev = await add_demo_device(other, "pro dev")
    now = dt(2026, 10, 22, 12, 0)
    clock.set_now(now)
    async with SessionLocal() as s:
        from app.services.readings import store_reading
        for d in (fdev, pdev):
            await store_reading(s, uuid.UUID(d["id"]), now - timedelta(days=40), {"pv_power": 1.0}, {})
            await store_reading(s, uuid.UUID(d["id"]), now - timedelta(days=30), {"pv_power": 1.5}, {})
            await store_reading(s, uuid.UUID(d["id"]), now - timedelta(days=3), {"pv_power": 2.0}, {})
        await s.commit()
    async with SessionLocal() as s:
        n = await purge_readings(s, now)
        await s.commit()
    # only the free tenant's 40 day old row: free keeps 7 days + 30 grace days (late renewals), home keeps 365
    assert n == 1
    await other.aclose()


# ------------------------------------------------------------------ eybond end to end through the API
@pytest.fixture
def cloud():
    c = FakeCloud()
    drv = get_driver("eybond_cloud")
    import httpx
    drv.transport = httpx.MockTransport(c.handler)
    drv.salt_fn = c.salt
    yield c
    drv.transport = None
    drv.salt_fn = None


async def test_drivers_endpoint(client):
    await register(client)
    drivers = {d["code"]: d for d in (await client.get("/api/drivers")).json()}
    assert set(drivers) == {"demo", "eybond_cloud"}
    e = drivers["eybond_cloud"]
    assert e["supports_control"] and e["supports_discovery"] and e["kind"] == "inverter"
    assert [(f["key"], f["type"], f["required"]) for f in e["credential_fields"]] == [("username", "text", True), ("password", "password", True)]
    assert {"label", "label_ar"} <= set(e["credential_fields"][0])
    assert drivers["demo"]["credential_fields"] == []


async def test_discover_then_add_eybond_device_encrypts_credentials(client, cloud):
    me = await register(client)
    sites = (await client.get("/api/sites")).json()
    r = await client.post("/api/integrations/discover", json={"driver": "eybond_cloud", "credentials": {"username": "user@example.com", "password": "wrong"}})
    assert r.status_code == 400 and r.json()["error"]["code"] == "integration_auth_failed"
    assert (await client.post("/api/integrations/discover", json={"driver": "eybond_cloud", "credentials": {}})).status_code == 422
    assert (await client.post("/api/integrations/discover", json={"driver": "nope", "credentials": {}})).status_code == 400
    r = await client.post("/api/integrations/discover", json={"driver": "eybond_cloud", "credentials": CREDS})
    assert r.status_code == 200
    disc = r.json()
    assert disc["devices"][0]["external_id"] == EXT and disc["devices"][0]["serial"] == "96322507123757"
    assert "secret-pass" not in disc["integration_token"]  # opaque encrypted blob

    r = await client.post("/api/devices", json={"site_id": sites[0]["id"], "driver": "eybond_cloud", "integration_token": disc["integration_token"],
                                                 "external_id": EXT, "name": "Home Inverter"})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["serial"] == "96322507123757" and d["driver"] == "eybond_cloud" and d["kind"] == "inverter"
    assert d["last_metrics"]["battery_soc"] == 87 and d["online"] is True  # first poll ran immediately
    # credentials are Fernet-encrypted at rest and only decryptable by the app
    async with SessionLocal() as s:
        raw = (await s.execute(text("SELECT credentials_enc FROM devices"))).scalar_one()
        assert "secret-pass" not in raw and "user@example.com" not in raw
        assert decrypt_json(raw) == CREDS
    live = (await client.get(f"/api/devices/{d['id']}/live")).json()
    assert live["metrics"]["pv_power"] == 1180 and live["raw"]["day_row"]["Machine Type"] == "Off-Grid"
    # duplicate
    r = await client.post("/api/devices", json={"site_id": sites[0]["id"], "driver": "eybond_cloud", "credentials": CREDS, "external_id": EXT, "name": "again"})
    assert r.status_code in (403, 409)  # free plan limit hits first
    await set_plan(me["tenant"]["id"], "home")
    r = await client.post("/api/devices", json={"site_id": sites[0]["id"], "driver": "eybond_cloud", "credentials": CREDS, "external_id": EXT, "name": "again"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "device_exists"
    # settings through the vendor API


async def test_eybond_control_end_to_end(client, cloud):
    me = await register(client)
    await set_plan(me["tenant"]["id"], "home")
    sites = (await client.get("/api/sites")).json()
    d = (await client.post("/api/devices", json={"site_id": sites[0]["id"], "driver": "eybond_cloud", "credentials": CREDS,
                                                  "external_id": EXT, "name": "Inv"})).json()
    s = {x["key"]: x for x in (await client.get(f"/api/devices/{d['id']}/settings")).json()}
    assert s["max_ac_charge_current"]["value"] == 30 and s["output_priority"]["value"] == "1"
    r = await client.post(f"/api/devices/{d['id']}/settings", json={"key": "max_ac_charge_current", "value": 40, "confirm": True})
    assert r.status_code == 200 and r.json()["old_value"] == 30 and r.json()["new_value"] == 40
    assert cloud.written == [("std_max_ac_chg", "40")]
    r = await client.post(f"/api/devices/{d['id']}/settings", json={"key": "max_ac_charge_current", "value": 90, "confirm": True})
    assert r.status_code == 422 and cloud.written == [("std_max_ac_chg", "40")]  # nothing was sent to the device
    r = await client.post(f"/api/devices/{d['id']}/settings", json={"key": "battery_cutoff_voltage", "value": 17, "confirm": True})
    assert r.status_code == 422


async def test_integration_token_is_bound_to_tenant_and_driver(client, cloud):
    await register(client)
    sites = (await client.get("/api/sites")).json()
    disc = (await client.post("/api/integrations/discover", json={"driver": "eybond_cloud", "credentials": CREDS})).json()
    other = make_client()
    await register(other)
    osites = (await other.get("/api/sites")).json()
    r = await other.post("/api/devices", json={"site_id": osites[0]["id"], "driver": "eybond_cloud", "integration_token": disc["integration_token"], "external_id": EXT, "name": "x"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "integration_token_invalid"
    r = await client.post("/api/devices", json={"site_id": sites[0]["id"], "driver": "demo", "integration_token": disc["integration_token"], "external_id": "demo-1", "name": "x"})
    assert r.status_code == 400
    r = await client.post("/api/devices", json={"site_id": sites[0]["id"], "driver": "eybond_cloud", "integration_token": "garbage", "external_id": EXT, "name": "x"})
    assert r.status_code == 400
    await other.aclose()


# ------------------------------------------------------------------ CLI
async def test_cli_seed_plans_superadmin_and_demo(client):
    assert "created superadmin" in await cli.create_superadmin("boss@example.com", "bosspass123")
    c = make_client()
    r = await c.post("/api/auth/login", json={"email": "boss@example.com", "password": "bosspass123"})
    assert r.status_code == 200 and r.json()["user"]["is_superadmin"] is True
    assert (await c.get("/api/admin/stats")).status_code == 200
    assert "promoted" in await cli.create_superadmin("boss@example.com", "newpass12345")

    msg = await cli.seed_demo(backfill_hours=3)
    assert "demo@syriana.energy" in msg
    d = make_client()
    r = await d.post("/api/auth/login", json={"email": "demo@syriana.energy", "password": "demo12345"})
    assert r.status_code == 200 and r.json()["tenant"]["plan"]["code"] == "pro"
    devs = (await d.get("/api/devices")).json()
    assert len(devs) == 1 and devs[0]["driver"] == "demo" and devs[0]["last_metrics"]
    h = (await d.get(f"/api/devices/{devs[0]['id']}/history?metrics=pv_power&bucket=15m&from={(clock.utcnow() - timedelta(hours=4)).strftime('%Y-%m-%dT%H:%M:%SZ')}")).json()
    assert len(h["series"]["pv_power"]) >= 10  # backfilled history
    assert "demo ready" in await cli.seed_demo(backfill_hours=3)  # idempotent
    assert len((await d.get("/api/devices")).json()) == 1
    await c.aclose(); await d.aclose()
