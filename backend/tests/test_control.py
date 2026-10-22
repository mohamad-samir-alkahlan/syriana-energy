from sqlalchemy import select

from app.db import SessionLocal
from app.drivers.base import DriverError
from app.drivers.registry import get_driver
from app.models import AuditLog, Command
from tests.conftest import make_client, register, set_plan


async def test_settings_list_and_change_with_audit(home):
    c, d = home["client"], home["device"]
    s = {x["key"]: x for x in (await c.get(f"/api/devices/{d['id']}/settings")).json()}
    assert s["max_ac_charge_current"]["type"] == "number" and s["max_ac_charge_current"]["min"] == 10
    assert s["output_priority"]["options"][0].keys() >= {"value", "label", "label_ar"}

    r = await c.post(f"/api/devices/{d['id']}/settings", json={"key": "max_ac_charge_current", "value": 50, "confirm": True})
    assert r.status_code == 200
    cmd = r.json()
    assert cmd["status"] == "ok" and cmd["old_value"] == 30 and cmd["new_value"] == 50 and cmd["user_name"] == "Test"
    # persisted in the device state: settings and live metrics reflect it
    s = {x["key"]: x["value"] for x in (await c.get(f"/api/devices/{d['id']}/settings")).json()}
    assert s["max_ac_charge_current"] == 50
    r = await c.post(f"/api/devices/{d['id']}/settings", json={"key": "output_priority", "value": "USB", "confirm": True})
    assert r.json()["old_value"] == "SUB"
    cmds = (await c.get(f"/api/devices/{d['id']}/commands")).json()
    assert cmds["total"] == 2 and cmds["items"][0]["key"] == "output_priority"

    async with SessionLocal() as db:
        actions = [a.action for a in (await db.execute(select(AuditLog).order_by(AuditLog.id))).scalars()]
    assert actions.count("setting.change") == 2 and actions.count("setting.result") == 2


async def test_confirm_required(home):
    c, d = home["client"], home["device"]
    for body in ({"key": "buzzer", "value": False}, {"key": "buzzer", "value": False, "confirm": False}):
        r = await c.post(f"/api/devices/{d['id']}/settings", json=body)
        assert r.status_code == 400 and r.json()["error"]["code"] == "confirm_required"
    s = {x["key"]: x["value"] for x in (await c.get(f"/api/devices/{d['id']}/settings")).json()}
    assert s["buzzer"] is True  # unchanged
    async with SessionLocal() as db:
        assert (await db.execute(select(Command))).first() is None


async def test_unsafe_values_rejected_and_audited(home):
    c, d = home["client"], home["device"]
    for key, val in [("max_ac_charge_current", 100), ("max_ac_charge_current", 0), ("max_ac_charge_current", 35),
                     ("max_ac_charge_current", "lots"), ("output_priority", "NOPE"), ("buzzer", "off")]:
        r = await c.post(f"/api/devices/{d['id']}/settings", json={"key": key, "value": val, "confirm": True})
        assert r.status_code == 422 and r.json()["error"]["code"] == "unsafe_value", (key, val, r.text)
    r = await c.post(f"/api/devices/{d['id']}/settings", json={"key": "does_not_exist", "value": 1, "confirm": True})
    assert r.status_code == 404 and r.json()["error"]["code"] == "setting_not_found"
    async with SessionLocal() as db:
        rejected = (await db.execute(select(AuditLog).where(AuditLog.action == "setting.rejected"))).scalars().all()
        assert len(rejected) == 6
        assert (await db.execute(select(Command))).first() is None


async def test_device_failure_is_recorded_as_failed_command(home, monkeypatch):
    c, d = home["client"], home["device"]
    drv = get_driver("demo")

    async def boom(device, key, value):
        raise DriverError("cloud said no", code="vendor_error")
    monkeypatch.setattr(drv, "write_setting", boom)
    r = await c.post(f"/api/devices/{d['id']}/settings", json={"key": "buzzer", "value": False, "confirm": True})
    assert r.status_code == 502 and r.json()["error"]["code"] == "device_error"
    cmds = (await c.get(f"/api/devices/{d['id']}/commands")).json()["items"]
    assert cmds[0]["status"] == "failed" and "cloud said no" in cmds[0]["error"]


async def test_control_requires_feature_and_role(client):
    me = await register(client)  # free plan
    sites = (await client.get("/api/sites")).json()
    d = (await client.post("/api/devices", json={"site_id": sites[0]["id"], "driver": "demo", "credentials": {},
                                                  "external_id": "demo-1", "name": "D"})).json()
    r = await client.get(f"/api/devices/{d['id']}/settings")
    assert r.status_code == 403 and r.json()["error"]["code"] == "feature_not_in_plan"
    r = await client.post(f"/api/devices/{d['id']}/settings", json={"key": "buzzer", "value": False, "confirm": True})
    assert r.status_code == 403 and r.json()["error"]["code"] == "feature_not_in_plan"

    await set_plan(me["tenant"]["id"], "home")
    assert (await client.get(f"/api/devices/{d['id']}/settings")).status_code == 200
    # a viewer in the same tenant cannot control
    r = await client.post("/api/users", json={"email": "viewer@example.com", "name": "V", "role": "viewer", "password": "viewerpass1"})
    assert r.status_code == 201
    v = make_client()
    assert (await v.post("/api/auth/login", json={"email": "viewer@example.com", "password": "viewerpass1"})).status_code == 200
    assert (await v.get(f"/api/devices/{d['id']}/live")).status_code == 200  # can read
    r = await v.post(f"/api/devices/{d['id']}/settings", json={"key": "buzzer", "value": False, "confirm": True})
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    assert (await v.delete(f"/api/devices/{d['id']}")).status_code == 403
    await v.aclose()
