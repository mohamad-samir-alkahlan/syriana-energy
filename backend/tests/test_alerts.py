"""Alert rules: firing, hysteresis, cooldown, grid transitions, overload duration, offline, daily summary, delivery."""
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Alert, AlertRule, Device, Tenant
from app.services import alerts as al
from app.services import readings as rd
from app.services.tenants import effective_plan
from tests.conftest import add_demo_device, dt, register, set_plan

T0 = dt(2026, 10, 22, 12, 0)


async def setup(client, plan="pro"):
    me = await register(client, locale="en")
    await set_plan(me["tenant"]["id"], plan)
    dev = await add_demo_device(client)
    return me, dev


async def feed(dev_id, tenant_id, metrics, now, prev=None, store=True):
    """Run the engine for one reading (and store it, like the poller does)."""
    async with SessionLocal() as s:
        d = await s.get(Device, uuid.UUID(dev_id))
        t = await s.get(Tenant, uuid.UUID(tenant_id))
        plan = await effective_plan(s, t)
        if store:
            await rd.store_reading(s, d.id, now, metrics, {})
        out = await al.process_reading(s, d, t, plan, metrics, prev, now)
        await s.commit()
        return out


async def clear_state(dev_id):
    async with SessionLocal() as s:
        from sqlalchemy import delete
        from app.models import AlertState
        await s.execute(delete(AlertState))
        await s.execute(delete(Alert))
        await s.commit()


async def test_default_rules_seeded(client):
    me = await register(client)
    rules = {r["type"]: r for r in (await client.get("/api/alert-rules")).json()}
    assert set(rules) == {"battery_low", "grid_lost", "grid_restored", "overload", "fault", "device_offline", "daily_summary"}
    assert rules["battery_low"]["params"] == {"threshold_soc": 30}
    assert rules["overload"]["params"] == {"threshold_percent": 90, "minutes": 3}
    assert rules["device_offline"]["params"] == {"minutes": 10} and rules["daily_summary"]["params"] == {"hour_local": 21}
    assert all(r["channels"] == ["inapp", "telegram"] and r["enabled"] for r in rules.values())


async def test_battery_low_fires_once_with_hysteresis_and_cooldown(client, fake):
    me, dev = await setup(client)
    tid, did = me["tenant"]["id"], dev["id"]
    await clear_state(did)
    assert await feed(did, tid, {"battery_soc": 45.0}, T0) == []
    out = await feed(did, tid, {"battery_soc": 29.0}, T0 + timedelta(minutes=1))
    assert [a["type"] for a in out] == ["battery_low"] and out[0]["severity"] == "warning"
    # still low: no repeat
    assert await feed(did, tid, {"battery_soc": 27.0}, T0 + timedelta(minutes=2)) == []
    # recovers a little (inside hysteresis band) and dips again: still no repeat
    assert await feed(did, tid, {"battery_soc": 33.0}, T0 + timedelta(minutes=3)) == []
    assert await feed(did, tid, {"battery_soc": 28.0}, T0 + timedelta(minutes=4)) == []
    # fully recovers, dips within the 60 min cooldown -> suppressed
    await feed(did, tid, {"battery_soc": 60.0}, T0 + timedelta(minutes=10))
    assert await feed(did, tid, {"battery_soc": 20.0}, T0 + timedelta(minutes=20)) == []
    # still low after the cooldown => fires
    out = await feed(did, tid, {"battery_soc": 19.0}, T0 + timedelta(minutes=70))
    assert [a["type"] for a in out] == ["battery_low"]
    items = (await client.get("/api/alerts")).json()["items"]
    assert [i["type"] for i in items].count("battery_low") == 2
    first = [i for i in items if i["type"] == "battery_low"][-1]
    assert "29%" in first["title"] and "29" in first["body"] and "٪" not in first["title_ar"] and first["title_ar"].startswith("البطارية منخفضة")


async def test_delivery_telegram_in_owner_locale_and_inapp(client, fake):
    me, dev = await setup(client)
    async with SessionLocal() as s:
        t = await s.get(Tenant, uuid.UUID(me["tenant"]["id"]))
        t.telegram_chats = [{"chat_id": 111, "title": "me"}, {"chat_id": 222, "title": "wife"}]
        await s.commit()
    await clear_state(dev["id"])
    await feed(dev["id"], me["tenant"]["id"], {"battery_soc": 10.0}, T0)
    assert {m[0] for m in fake.telegram_msgs} == {111, 222}
    assert "Battery low" in fake.telegram_msgs[0][1]  # owner locale is en
    # rule without telegram => only the in-app row
    rid = [r for r in (await client.get("/api/alert-rules")).json() if r["type"] == "battery_low"][0]["id"]
    await client.patch(f"/api/alert-rules/{rid}", json={"channels": ["inapp"]})
    await clear_state(dev["id"])
    fake.telegram_msgs.clear()
    await feed(dev["id"], me["tenant"]["id"], {"battery_soc": 10.0}, T0 + timedelta(hours=5))
    assert fake.telegram_msgs == []
    assert (await client.get("/api/alerts")).json()["total"] == 1
    # rule without inapp => telegram only, no alert row
    await client.patch(f"/api/alert-rules/{rid}", json={"channels": ["telegram"]})
    await clear_state(dev["id"])
    await feed(dev["id"], me["tenant"]["id"], {"battery_soc": 10.0}, T0 + timedelta(hours=9))
    assert len(fake.telegram_msgs) == 2 and (await client.get("/api/alerts")).json()["total"] == 0


async def test_arabic_owner_gets_arabic_telegram(client, fake):
    me = await register(client, locale="ar")
    dev = await add_demo_device(client)
    async with SessionLocal() as s:
        t = await s.get(Tenant, uuid.UUID(me["tenant"]["id"]))
        t.telegram_chats = [{"chat_id": 5, "title": "x"}]
        await s.commit()
    await clear_state(dev["id"])
    await feed(dev["id"], me["tenant"]["id"], {"battery_soc": 10.0}, T0)
    assert "البطارية منخفضة" in fake.telegram_msgs[0][1]


async def test_email_and_webhook_channels_follow_plan(client, fake):
    me, dev = await setup(client, "home")
    fake.emails.clear()  # drop the sign-up confirmation mail
    r = await client.patch("/api/channels", json={"email": {"enabled": True, "address": "owner@example.com"}})
    assert r.status_code == 200 and r.json()["email"] == {"enabled": True, "address": "owner@example.com"}
    assert (await client.patch("/api/channels", json={"webhook": {"enabled": True, "url": "http://127.0.0.1/hook"}})).status_code == 422
    assert (await client.patch("/api/channels", json={"webhook": {"enabled": True, "url": "ftp://x/y"}})).status_code == 422
    r = await client.patch("/api/channels", json={"webhook": {"enabled": True, "url": "https://8.8.8.8/hook"}})
    assert r.status_code == 200
    rid = [r for r in (await client.get("/api/alert-rules")).json() if r["type"] == "grid_lost"][0]["id"]
    assert (await client.patch(f"/api/alert-rules/{rid}", json={"channels": ["inapp", "email", "webhook"]})).status_code == 200
    await clear_state(dev["id"])
    await feed(dev["id"], me["tenant"]["id"], {"grid_available": False, "battery_soc": 80.0}, T0, prev={"grid_available": True})
    assert fake.emails and fake.emails[0][0] == "owner@example.com" and "Grid power lost" in fake.emails[0][1]
    assert fake.webhooks and fake.webhooks[0][1]["type"] == "grid_lost" and fake.webhooks[0][1]["title_ar"]
    # downgrade: delivery to email/webhook stops even though the rule still lists them
    await set_plan(me["tenant"]["id"], "free")
    fake.emails.clear(); fake.webhooks.clear()
    await clear_state(dev["id"])
    await feed(dev["id"], me["tenant"]["id"], {"grid_available": False}, T0 + timedelta(hours=1), prev={"grid_available": True})
    assert fake.emails == [] and fake.webhooks == []


async def test_grid_lost_restored_transitions_and_duration(client, fake):
    me, dev = await setup(client)
    tid, did = me["tenant"]["id"], dev["id"]
    await clear_state(did)
    # the very first reading has no previous state: no alert
    assert await feed(did, tid, {"grid_available": False}, T0) == []
    lost = await feed(did, tid, {"grid_available": False, "battery_soc": 90.0}, T0 + timedelta(minutes=1), prev={"grid_available": True})
    assert [a["type"] for a in lost] == ["grid_lost"]
    assert await feed(did, tid, {"grid_available": False}, T0 + timedelta(minutes=2), prev={"grid_available": False}) == []
    # keep readings so the engine can compute how long the outage lasted
    async with SessionLocal() as s:
        await rd.store_reading(s, uuid.UUID(did), T0 - timedelta(minutes=30), {"grid_available": True}, {})
        await s.commit()
    back = await feed(did, tid, {"grid_available": True}, T0 + timedelta(minutes=95), prev={"grid_available": False})
    assert [a["type"] for a in back] == ["grid_restored"]
    items = (await client.get("/api/alerts")).json()["items"]
    restored = [i for i in items if i["type"] == "grid_restored"][0]
    assert restored["severity"] == "info" and "Outage lasted" in restored["body"] and "1h" in restored["body"]
    # a new outage right away is a genuine new event (separate rule), but a "restored" flap inside the 5 min cooldown is not
    assert [a["type"] for a in await feed(did, tid, {"grid_available": False}, T0 + timedelta(minutes=96), prev={"grid_available": True})] == ["grid_lost"]
    assert await feed(did, tid, {"grid_available": True}, T0 + timedelta(minutes=97), prev={"grid_available": False}) == []
    assert [a["type"] for a in await feed(did, tid, {"grid_available": True}, T0 + timedelta(minutes=104), prev={"grid_available": False})] == ["grid_restored"]


async def test_overload_requires_sustained_minutes(client, fake):
    me, dev = await setup(client)
    tid, did = me["tenant"]["id"], dev["id"]
    await clear_state(did)
    hi = {"load_percent": 95.0}
    assert await feed(did, tid, hi, T0) == []
    assert await feed(did, tid, hi, T0 + timedelta(minutes=2)) == []
    out = await feed(did, tid, hi, T0 + timedelta(minutes=3, seconds=5))
    assert [a["type"] for a in out] == ["overload"] and out[0]["severity"] == "critical"
    assert await feed(did, tid, hi, T0 + timedelta(minutes=4)) == []  # already active
    # a dip resets the timer: a later spike needs another 3 minutes
    assert await feed(did, tid, {"load_percent": 40.0}, T0 + timedelta(minutes=5)) == []
    assert await feed(did, tid, hi, T0 + timedelta(minutes=30)) == []
    assert await feed(did, tid, hi, T0 + timedelta(minutes=32)) == []
    assert [a["type"] for a in await feed(did, tid, hi, T0 + timedelta(minutes=34))] == ["overload"]


async def test_fault_rule_modes_and_codes(client):
    me, dev = await setup(client)
    tid, did = me["tenant"]["id"], dev["id"]
    await clear_state(did)
    assert await feed(did, tid, {"mode": "line", "fault_codes": []}, T0) == []
    out = await feed(did, tid, {"mode": "fault"}, T0 + timedelta(minutes=1))
    assert [a["type"] for a in out] == ["fault"]
    await feed(did, tid, {"mode": "line"}, T0 + timedelta(minutes=2))  # clears
    out = await feed(did, tid, {"mode": "battery", "fault_codes": ["F07: Overload"]}, T0 + timedelta(minutes=40))
    assert [a["type"] for a in out] == ["fault"] and "F07" in out[0]["body"]


async def test_device_offline_and_rearm(client, fake):
    me, dev = await setup(client)
    tid, did = me["tenant"]["id"], dev["id"]
    await clear_state(did)
    async with SessionLocal() as s:
        d = await s.get(Device, uuid.UUID(did))
        d.last_seen = T0
        await s.commit()
    async with SessionLocal() as s:
        assert await al.check_offline(s, T0 + timedelta(minutes=9)) == []
        out = await al.check_offline(s, T0 + timedelta(minutes=11))
        assert [a["type"] for a in out] == ["device_offline"]
        assert await al.check_offline(s, T0 + timedelta(minutes=30)) == []  # no spam
        await s.commit()
    # data returns => re-armed; a second outage after the cooldown alerts again
    await feed(did, tid, {"battery_soc": 80.0}, T0 + timedelta(minutes=40))
    async with SessionLocal() as s:
        d = await s.get(Device, uuid.UUID(did))
        d.last_seen = T0 + timedelta(minutes=40)
        await s.commit()
        out = await al.check_offline(s, T0 + timedelta(minutes=40 + 12 + 60))
        await s.commit()
    assert [a["type"] for a in out] == ["device_offline"]


async def test_daily_summary_once_per_local_day(client):
    me, dev = await setup(client)
    await clear_state(dev["id"])
    async with SessionLocal() as s:
        # 21:00 local = 18:00 UTC. Put some data in today's window.
        for i in range(0, 60, 5):
            await rd.store_reading(s, uuid.UUID(dev["id"]), dt(2026, 10, 22, 9, 0) + timedelta(minutes=i),
                                   {"pv_power": 1000.0, "load_power": 500.0, "grid_available": True, "mode": "line"}, {})
        await s.commit()
        assert await al.check_daily_summary(s, dt(2026, 10, 22, 17, 59)) == []  # 20:59 local
        out = await al.check_daily_summary(s, dt(2026, 10, 22, 18, 5))
        assert len(out) == 1 and out[0]["type"] == "daily_summary" and out[0]["severity"] == "info"
        assert await al.check_daily_summary(s, dt(2026, 10, 22, 19, 0)) == []
        out2 = await al.check_daily_summary(s, dt(2026, 10, 23, 18, 5))
        assert len(out2) == 1
        await s.commit()
    body = (await client.get("/api/alerts")).json()["items"][-1]["body"]
    assert "solar 0.9" in body or "solar 1.0" in body or "solar" in body


async def test_rule_crud_validation(client):
    me = await register(client)
    r = await client.post("/api/alert-rules", json={"type": "high_temperature", "params": {"threshold_c": 70}})
    assert r.status_code == 201 and r.json()["params"] == {"threshold_c": 70} and r.json()["cooldown_minutes"] == 30
    rid = r.json()["id"]
    assert (await client.post("/api/alert-rules", json={"type": "nonsense"})).status_code == 422
    assert (await client.post("/api/alert-rules", json={"type": "battery_low", "params": {"threshold_soc": 500}})).status_code == 422
    assert (await client.post("/api/alert-rules", json={"type": "battery_low", "params": {"bogus": 1}})).status_code == 422
    assert (await client.post("/api/alert-rules", json={"type": "battery_low", "channels": ["sms"]})).status_code == 422
    r = await client.patch(f"/api/alert-rules/{rid}", json={"enabled": False, "params": {"threshold_c": 65}, "cooldown_minutes": 5})
    assert r.json()["enabled"] is False and r.json()["params"]["threshold_c"] == 65 and r.json()["cooldown_minutes"] == 5
    assert (await client.delete(f"/api/alert-rules/{rid}")).status_code == 204
    # disabled rules never fire
    me2 = await register(client, locale="en")
    dev = await add_demo_device(client)
    await clear_state(dev["id"])
    for r in (await client.get("/api/alert-rules")).json():
        await client.patch(f"/api/alert-rules/{r['id']}", json={"enabled": False})
    assert await feed(dev["id"], me2["tenant"]["id"], {"battery_soc": 1.0, "mode": "fault"}, T0) == []


async def test_alert_feed_read_and_pagination(client):
    me = await register(client)
    async with SessionLocal() as s:
        for i in range(5):
            s.add(Alert(tenant_id=uuid.UUID(me["tenant"]["id"]), type="x", title=f"t{i}", title_ar=f"ع{i}",
                        created_at=T0 + timedelta(minutes=i)))
        await s.commit()
    page = (await client.get("/api/alerts?limit=2&offset=0")).json()
    assert page["total"] == 5 and page["unread"] == 5 and [a["title"] for a in page["items"]] == ["t4", "t3"]
    assert page["items"][0]["read"] is False and {"id", "device_id", "device_name", "severity", "body_ar"} <= set(page["items"][0])
    assert (await client.post(f"/api/alerts/{page['items'][0]['id']}/read")).json()["read"] is True
    assert (await client.get("/api/alerts?limit=1")).json()["unread"] == 4
    assert (await client.post("/api/alerts/read-all")).status_code == 200
    assert (await client.get("/api/alerts")).json()["unread"] == 0
