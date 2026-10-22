"""History buckets/clamping, energy integration (trapezoid), today summary, outages, battery runtime."""
import uuid
from datetime import timedelta

import pytest

from app import clock
from app.db import SessionLocal
from app.models import Device
from app.services import readings as rd
from tests.conftest import dt, register, set_plan


async def insert(device_id, rows):
    async with SessionLocal() as s:
        for ts, m in rows:
            await rd.store_reading(s, uuid.UUID(device_id), ts, m, {})
        await s.commit()


async def mk_device(client, plan="pro"):
    me = await register(client)
    await set_plan(me["tenant"]["id"], plan)
    sites = (await client.get("/api/sites")).json()
    # create without the immediate demo poll noise: use eybond-less demo device then wipe its readings
    r = await client.post("/api/devices", json={"site_id": sites[0]["id"], "driver": "demo", "credentials": {},
                                                 "external_id": "demo-x", "name": "D"})
    d = r.json()
    async with SessionLocal() as s:
        from sqlalchemy import delete
        from app.models import Reading
        await s.execute(delete(Reading))
        await s.commit()
    return me, d


async def test_energy_trapezoid_and_gap_handling(client):
    clock.set_now(dt(2026, 10, 22, 12, 0))
    me, d = await mk_device(client)
    base = dt(2026, 10, 22, 6, 0)  # 09:00 local
    # 1000 W flat for 1h => 1.0 kWh pv; load ramps 0 -> 600 W over 1h => 0.3 kWh (trapezoid)
    rows = []
    for i in range(0, 61, 5):
        rows.append((base + timedelta(minutes=i), {"pv_power": 1000.0, "load_power": 10.0 * i, "grid_available": False}))
    # a 2h data gap, then 2 more points (the gap segment must NOT be integrated)
    rows.append((base + timedelta(hours=3), {"pv_power": 1000.0, "load_power": 0.0}))
    rows.append((base + timedelta(hours=3, minutes=5), {"pv_power": 1000.0, "load_power": 0.0}))
    await insert(d["id"], rows)
    e = (await client.get(f"/api/devices/{d['id']}/energy?days=1")).json()
    assert len(e) == 1 and e[0]["date"] == "2026-10-22"
    assert e[0]["pv_kwh"] == pytest.approx(1.0 + 1000 * 5 / 60 / 1000, abs=1e-3)  # 1h + the 5 min after the gap
    assert e[0]["load_kwh"] == pytest.approx(0.3, abs=1e-3)
    assert e[0]["grid_kwh"] == 0


async def test_grid_energy_derived_and_explicit(client):
    clock.set_now(dt(2026, 10, 22, 12, 0))
    me, d = await mk_device(client)
    t = dt(2026, 10, 22, 4, 0)
    # derived: line mode + grid available => grid supplies the load (600W for 30 min = 0.3 kWh)
    await insert(d["id"], [(t + timedelta(minutes=5 * i), {"load_power": 600.0, "grid_available": True, "mode": "line"})
                           for i in range(7)])
    # explicit grid_power wins (1200 W for 30 min = 0.6 kWh)
    t2 = dt(2026, 10, 22, 7, 0)
    await insert(d["id"], [(t2 + timedelta(minutes=5 * i), {"load_power": 600.0, "grid_power": 1200.0, "grid_available": True, "mode": "line"})
                           for i in range(7)])
    e = (await client.get(f"/api/devices/{d['id']}/energy?days=1")).json()
    assert e[0]["grid_kwh"] == pytest.approx(0.9, abs=1e-3)


async def test_energy_days_fill_zero_days_and_clamp(client):
    clock.set_now(dt(2026, 10, 22, 12, 0))
    me, d = await mk_device(client, "free")  # 7 history days
    e = (await client.get(f"/api/devices/{d['id']}/energy?days=30")).json()
    assert len(e) == 7 and e[-1]["date"] == "2026-10-22" and e[0]["date"] == "2026-10-16"
    assert all(x["pv_kwh"] == 0 for x in e)


async def test_today_outages_and_runtime(client):
    clock.set_now(dt(2026, 10, 22, 12, 0))  # 15:00 local; local midnight = 21:00 UTC the day before
    me, d = await mk_device(client)
    t = dt(2026, 10, 22, 1, 0)
    pattern = [True, True, False, False, False, True, True, False]  # outage1: idx2-4, outage2 starts at idx7 (ongoing)
    await insert(d["id"], [(t + timedelta(minutes=10 * i), {"grid_available": g, "load_power": 500.0}) for i, g in enumerate(pattern)])
    async with SessionLocal() as s:
        dev = await s.get(Device, uuid.UUID(d["id"]))
        dev.last_metrics = None
        await s.commit()
    today = (await client.get(f"/api/devices/{d['id']}/today")).json()
    assert len(today["grid_outages"]) == 2
    o1, o2 = today["grid_outages"]
    assert o1["from"].startswith("2026-10-22T01:20") and o1["to"].startswith("2026-10-22T01:50")
    assert o2["from"].startswith("2026-10-22T02:10") and o2["to"] is None  # still ongoing
    assert today["pv_kwh"] == 0 and today["battery_runtime_hours"] is None  # no live data on the device row

    async with SessionLocal() as s:
        dev = await s.get(Device, uuid.UUID(d["id"]))
        dev.last_metrics = {"battery_soc": 70.0, "load_power": 480.0}
        dev.battery_capacity_wh = 4800.0
        await s.commit()
    today = (await client.get(f"/api/devices/{d['id']}/today")).json()
    assert today["battery_runtime_hours"] == pytest.approx((70 - 20) / 100 * 4800 / 480)  # 5.0 h
    # editable capacity changes the estimate
    r = await client.patch(f"/api/devices/{d['id']}", json={"battery_capacity_wh": 9600})
    assert r.json()["battery_capacity_wh"] == 9600
    today = (await client.get(f"/api/devices/{d['id']}/today")).json()
    assert today["battery_runtime_hours"] == pytest.approx(10.0)
    r = await client.patch(f"/api/devices/{d['id']}", json={"battery_capacity_wh": 5})
    assert r.status_code == 422


def test_runtime_edge_cases():
    assert rd.battery_runtime_hours(None, 4800) is None
    assert rd.battery_runtime_hours({"battery_soc": 15, "load_power": 500}, 4800) == 0.0
    assert rd.battery_runtime_hours({"battery_soc": 80, "load_power": 0}, 4800) is None


async def test_outage_already_running_at_midnight_uses_last_grid_seen(client):
    clock.set_now(dt(2026, 10, 22, 12, 0))
    me, d = await mk_device(client)
    await insert(d["id"], [
        (dt(2026, 10, 21, 20, 0), {"grid_available": True}),     # yesterday: last time the grid was seen
        (dt(2026, 10, 21, 22, 0), {"grid_available": False}),    # (after local midnight 21:00Z)
        (dt(2026, 10, 22, 2, 0), {"grid_available": True})])
    today = (await client.get(f"/api/devices/{d['id']}/today")).json()
    assert len(today["grid_outages"]) == 1
    assert today["grid_outages"][0]["from"].startswith("2026-10-21T20:00") and today["grid_outages"][0]["to"].startswith("2026-10-22T02:00")


async def test_history_buckets_and_raw(client):
    clock.set_now(dt(2026, 10, 22, 12, 0))
    me, d = await mk_device(client)
    t = dt(2026, 10, 22, 10, 0)
    await insert(d["id"], [(t + timedelta(minutes=i), {"pv_power": float(i), "battery_soc": 50.0, "grid_available": i < 30})
                           for i in range(60)])
    q = f"/api/devices/{d['id']}/history?from=2026-10-22T10:00:00Z&to=2026-10-22T11:00:00Z&metrics=pv_power,battery_soc,grid_available"
    h = (await client.get(q + "&bucket=15m")).json()
    assert h["bucket"] == "15m"
    pv = h["series"]["pv_power"]
    assert len(pv) == 4 and pv[0][0] == "2026-10-22T10:00:00Z"
    assert pv[0][1] == pytest.approx(7.0) and pv[1][1] == pytest.approx(22.0) and pv[3][1] == pytest.approx(52.0)
    assert [p[1] for p in h["series"]["grid_available"]] == [1.0, 1.0, 0.0, 0.0]
    h = (await client.get(q + "&bucket=1h")).json()
    assert len(h["series"]["pv_power"]) == 1 and h["series"]["pv_power"][0][1] == pytest.approx(29.5)
    h = (await client.get(q + "&bucket=raw")).json()
    assert h["bucket"] == "raw" and len(h["series"]["pv_power"]) == 60
    h = (await client.get(q + "&bucket=1m")).json()
    assert len(h["series"]["battery_soc"]) == 60
    r = await client.get(q + "&bucket=2h")
    assert r.status_code == 400
    r = await client.get(f"/api/devices/{d['id']}/history?metrics=evil;drop")
    assert r.status_code == 400
    r = await client.get(f"/api/devices/{d['id']}/history?metrics=mode")  # non-numeric metrics are not chartable
    assert r.status_code == 400


async def test_history_daily_bucket_uses_local_days(client):
    clock.set_now(dt(2026, 10, 22, 12, 0))
    me, d = await mk_device(client)
    await insert(d["id"], [(dt(2026, 10, 20, 12, 0), {"pv_power": 100.0}), (dt(2026, 10, 21, 12, 0), {"pv_power": 300.0}),
                           (dt(2026, 10, 21, 13, 0), {"pv_power": 500.0})])
    h = (await client.get(f"/api/devices/{d['id']}/history?from=2026-10-19T00:00:00Z&to=2026-10-22T00:00:00Z&metrics=pv_power&bucket=1d")).json()
    pts = h["series"]["pv_power"]
    assert len(pts) == 2 and pts[0][1] == 100.0 and pts[1][1] == 400.0
    assert pts[0][0] == "2026-10-19T21:00:00Z"  # local midnight (UTC+3) expressed in UTC


async def test_history_clamped_to_plan_days_and_auto_coarsens(client):
    clock.set_now(dt(2026, 10, 22, 12, 0))
    me, d = await mk_device(client, "free")
    await insert(d["id"], [(dt(2026, 10, 1, 12, 0), {"pv_power": 111.0}),   # 21 days old: outside the free window
                           (dt(2026, 10, 18, 12, 0), {"pv_power": 222.0})])  # inside 7 days
    h = (await client.get(f"/api/devices/{d['id']}/history?from=2026-09-01T00:00:00Z&to=2026-10-22T12:00:00Z&metrics=pv_power&bucket=1h")).json()
    assert [p[1] for p in h["series"]["pv_power"]] == [222.0]
    # raw over 7 days would exceed the point cap -> the server coarsens and says so
    h = (await client.get(f"/api/devices/{d['id']}/history?from=2026-10-15T12:00:00Z&to=2026-10-22T12:00:00Z&metrics=pv_power&bucket=raw")).json()
    assert h["bucket"] in ("1m", "5m", "15m", "1h")
    await set_plan(me["tenant"]["id"], "home")
    h = (await client.get(f"/api/devices/{d['id']}/history?from=2026-09-01T00:00:00Z&to=2026-10-22T12:00:00Z&metrics=pv_power&bucket=1d")).json()
    assert sorted(p[1] for p in h["series"]["pv_power"]) == [111.0, 222.0]


def test_parse_range_clamp():
    clock.set_now(dt(2026, 10, 22, 12, 0))
    frm, to = rd.parse_range(dt(2020, 1, 1), None, 7)
    assert frm == dt(2026, 10, 15, 12, 0) and to == dt(2026, 10, 22, 12, 0)
