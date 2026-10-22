"""Automations: hysteresis (fire once entering, recover once leaving), actions, grid filter."""
import uuid
from datetime import timedelta

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Command, Device, Tenant
from app.services import automations as au
from app.services.tenants import effective_plan
from tests.conftest import add_demo_device, dt, register, set_plan

T0 = dt(2026, 10, 22, 12, 0)


async def run(tid, did, metrics, now):
    async with SessionLocal() as s:
        d = await s.get(Device, uuid.UUID(did))
        t = await s.get(Tenant, uuid.UUID(tid))
        out = await au.run_for_reading(s, d, t, await effective_plan(s, t), metrics, now)
        await s.commit()
        return out


async def mk(client, **over):
    me = await register(client, locale="en")
    await set_plan(me["tenant"]["id"], "pro")
    dev = await add_demo_device(client)
    body = {"name": "Shed heater", "device_id": dev["id"],
            "conditions": [{"metric": "battery_soc", "op": "<", "value": 40}], "grid": "lost",
            "actions": [{"type": "http", "method": "POST", "url": "https://8.8.8.8/heater/off", "body": {"on": False}},
                        {"type": "notify", "message": "Heater shed"}],
            "recover_conditions": [{"metric": "battery_soc", "op": ">", "value": 60}],
            "recover_actions": [{"type": "http", "method": "POST", "url": "https://8.8.8.8/heater/on"}]}
    body.update(over)
    r = await client.post("/api/automations", json=body)
    assert r.status_code == 201, r.text
    return me, dev, r.json()


async def test_hysteresis_fires_once_and_recovers_once(client, fake):
    me, dev, a = await mk(client)
    tid, did = me["tenant"]["id"], dev["id"]
    assert a["state"] == "idle" and a["last_triggered_at"] is None
    # grid present => grid filter blocks it even though soc is low
    assert await run(tid, did, {"battery_soc": 30.0, "grid_available": True}, T0) == []
    assert await run(tid, did, {"battery_soc": 45.0, "grid_available": False}, T0 + timedelta(minutes=1)) == []
    assert await run(tid, did, {"battery_soc": 39.0, "grid_available": False}, T0 + timedelta(minutes=2)) == [("Shed heater", "triggered")]
    assert [c[:2] for c in fake.http_calls] == [("POST", "https://8.8.8.8/heater/off")]
    assert fake.http_calls[0][2] == {"on": False}
    # stays active; further low readings do not re-fire
    for i, soc in enumerate([38.0, 35.0, 41.0, 50.0, 59.0]):  # 41..59 is inside the hysteresis band
        assert await run(tid, did, {"battery_soc": soc, "grid_available": False}, T0 + timedelta(minutes=3 + i)) == []
    assert len(fake.http_calls) == 1
    cur = (await client.get(f"/api/automations/{a['id']}")).json()
    assert cur["state"] == "active" and cur["last_triggered_at"]
    # recover above 60 => recover actions once
    assert await run(tid, did, {"battery_soc": 61.0, "grid_available": False}, T0 + timedelta(minutes=10)) == [("Shed heater", "recovered")]
    assert fake.http_calls[-1][1] == "https://8.8.8.8/heater/on" and len(fake.http_calls) == 2
    assert await run(tid, did, {"battery_soc": 90.0, "grid_available": False}, T0 + timedelta(minutes=11)) == []
    assert (await client.get(f"/api/automations/{a['id']}")).json()["state"] == "idle"
    # can trigger again afterwards
    assert await run(tid, did, {"battery_soc": 20.0, "grid_available": False}, T0 + timedelta(minutes=20)) == [("Shed heater", "triggered")]
    # notify action produced in-app alerts
    alerts = (await client.get("/api/alerts")).json()["items"]
    assert [x["body"] for x in alerts].count("Heater shed") == 2 and alerts[0]["type"] == "automation"


async def test_recover_without_recover_conditions_uses_inverse(client, fake):
    me, dev, a = await mk(client, recover_conditions=[], grid="any")
    tid, did = me["tenant"]["id"], dev["id"]
    assert await run(tid, did, {"battery_soc": 10.0}, T0) == [("Shed heater", "triggered")]
    assert await run(tid, did, {"battery_soc": 12.0}, T0 + timedelta(minutes=1)) == []
    assert await run(tid, did, {"battery_soc": 41.0}, T0 + timedelta(minutes=2)) == [("Shed heater", "recovered")]


async def test_multiple_conditions_and_missing_metric(client, fake):
    me, dev, a = await mk(client, grid="any", recover_conditions=[],
                          conditions=[{"metric": "battery_soc", "op": "<=", "value": 50}, {"metric": "load_power", "op": ">", "value": 500}])
    tid, did = me["tenant"]["id"], dev["id"]
    assert await run(tid, did, {"battery_soc": 40.0}, T0) == []  # load_power missing => false
    assert await run(tid, did, {"battery_soc": 40.0, "load_power": 400.0}, T0 + timedelta(minutes=1)) == []
    assert await run(tid, did, {"battery_soc": 40.0, "load_power": 800.0}, T0 + timedelta(minutes=2)) == [("Shed heater", "triggered")]


async def test_setting_action_goes_through_control_and_audit(client, fake):
    me, dev, a = await mk(client, grid="lost", actions=[{"type": "setting", "key": "max_ac_charge_current", "value": 60}],
                          recover_actions=[{"type": "setting", "key": "max_ac_charge_current", "value": 20}])
    tid, did = me["tenant"]["id"], dev["id"]
    await run(tid, did, {"battery_soc": 10.0, "grid_available": False}, T0)
    await run(tid, did, {"battery_soc": 80.0, "grid_available": False}, T0 + timedelta(minutes=1))
    cmds = (await client.get(f"/api/devices/{did}/commands")).json()["items"]
    assert [(c["key"], c["new_value"], c["status"]) for c in cmds] == [("max_ac_charge_current", 20, "ok"), ("max_ac_charge_current", 60, "ok")]
    assert cmds[0]["user_name"] == "automation:Shed heater"
    # an unsafe value configured in an automation is refused by the same validation and reported in-app
    r = await client.patch(f"/api/automations/{a['id']}", json={"actions": [{"type": "setting", "key": "max_ac_charge_current", "value": 999}]})
    assert r.status_code == 200
    await run(tid, did, {"battery_soc": 10.0, "grid_available": False}, T0 + timedelta(minutes=5))
    alerts = (await client.get("/api/alerts")).json()["items"]
    assert any("failed" in x["body"] for x in alerts)


async def test_http_action_failure_is_reported_not_raised(client, fake):
    me, dev, a = await mk(client)
    fake.fail_http = True
    out = await run(me["tenant"]["id"], dev["id"], {"battery_soc": 10.0, "grid_available": False}, T0)
    assert out == [("Shed heater", "triggered")]
    assert any("failed" in x["body"] for x in (await client.get("/api/alerts")).json()["items"])


async def test_validation_and_disable(client):
    me, dev, a = await mk(client)
    bad = [{"conditions": []}, {"conditions": [{"metric": "nope", "op": "<", "value": 1}]},
           {"conditions": [{"metric": "battery_soc", "op": "~", "value": 1}]}, {"grid": "sometimes"},
           {"actions": [{"type": "rm_rf"}]}, {"actions": [{"type": "http", "method": "DELETE", "url": "http://x"}]},
           {"device_id": str(uuid.uuid4())}]
    for patch in bad:
        r = await client.post("/api/automations", json={"name": "bad", "conditions": [{"metric": "battery_soc", "op": "<", "value": 1}], **patch})
        assert r.status_code in (422, 404), (patch, r.status_code)
    r = await client.patch(f"/api/automations/{a['id']}", json={"enabled": False})
    assert r.json()["enabled"] is False
    assert await run(me["tenant"]["id"], dev["id"], {"battery_soc": 1.0, "grid_available": False}, T0) == []
    assert (await client.delete(f"/api/automations/{a['id']}")).status_code == 204
    assert (await client.get("/api/automations")).json() == []


def test_condition_helpers():
    assert au.conditions_met({"grid_available": False}, [{"metric": "grid_available", "op": "==", "value": 0}])
    assert au.conditions_met({"mode": "line"}, [{"metric": "mode", "op": "==", "value": "line"}])
    assert not au.conditions_met({"mode": "line"}, [{"metric": "mode", "op": "<", "value": 3}])
    assert not au.conditions_met({}, [])
    assert au.grid_matches({"grid_available": True}, "available") and not au.grid_matches({}, "lost")
