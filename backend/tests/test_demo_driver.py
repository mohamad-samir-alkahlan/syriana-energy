import copy
from datetime import timedelta

import pytest

from app import clock
from app.drivers import demo
from app.drivers.base import DeviceContext
from app.drivers.registry import get_driver
from tests.conftest import dt

TZ = "Asia/Damascus"  # UTC+3 in October 2026


def test_sun_curve_peaks_at_local_noon():
    noon = dt(2026, 10, 22, 9, 0)  # 12:00 Damascus
    assert 1100 <= demo.sun_power(noon, TZ) <= 1500
    assert demo.sun_power(dt(2026, 10, 22, 23, 0), TZ) == 0  # 02:00 local
    assert demo.sun_power(dt(2026, 10, 22, 3, 0), TZ) == 0   # 06:00 local, sunrise edge
    assert demo.sun_power(dt(2026, 10, 22, 6, 0), TZ) < demo.sun_power(dt(2026, 10, 22, 8, 0), TZ) < demo.sun_power(noon, TZ)


def test_load_bounds_and_evening_peak():
    vals = [demo.load_demand(dt(2026, 10, 22) + timedelta(minutes=10 * i), TZ) for i in range(144)]
    assert min(vals) >= 300 and max(vals) <= 900
    assert demo.load_demand(dt(2026, 10, 22, 17, 0), TZ) > demo.load_demand(dt(2026, 10, 22, 9, 0), TZ) + 200  # 20:00 vs 12:00


def test_grid_schedule_two_on_four_off():
    on = [demo.grid_on(dt(2026, 10, 22) + timedelta(minutes=m)) for m in range(0, 24 * 60, 5)]
    assert sum(on) * 5 == 8 * 60  # 2h on every 6h => 8h/day
    assert demo.grid_on(dt(2026, 10, 22, 0, 30)) and not demo.grid_on(dt(2026, 10, 22, 3, 0))


def test_soc_integrates_discharge_at_night():
    state = {"soc": 80.0, "settings": dict(demo.DEFAULT_SETTINGS)}
    start = dt(2026, 10, 22, 22, 0)  # 01:00 local, grid off (22:00 UTC -> phase 4h of the cycle)
    assert not demo.grid_on(start) and not demo.grid_on(start + timedelta(hours=1))
    demo.advance(state, 4800.0, TZ, start)
    f = demo.advance(state, 4800.0, TZ, start + timedelta(hours=1))
    # load ~300W/0.94 for an hour out of 4800Wh => ~6.6% drop
    assert 72.0 < state["soc"] < 76.5
    assert f["batt"] < 0 and f["pv"] == 0 and f["mode"] == "battery"


def test_charges_from_grid_when_available():
    state = {"soc": 40.0, "settings": {**demo.DEFAULT_SETTINGS, "output_priority": "USB", "charger_priority": "SNU",
                                        "max_ac_charge_current": 20}}
    t0 = dt(2026, 10, 22, 0, 0)  # grid on for the first 2h of every 6h cycle
    demo.advance(state, 4800.0, TZ, t0)
    f = demo.advance(state, 4800.0, TZ, t0 + timedelta(minutes=30))
    assert f["mode"] == "line" and f["batt"] > 400 and f["grid"] > f["load"]
    assert state["soc"] > 40.0


def test_deterministic():
    s1 = {"soc": 60.0, "settings": dict(demo.DEFAULT_SETTINGS)}
    s2 = copy.deepcopy(s1)
    t = dt(2026, 10, 22, 8, 0)
    for s in (s1, s2):
        demo.advance(s, 4800.0, TZ, t)
        demo.advance(s, 4800.0, TZ, t + timedelta(minutes=17))
    assert s1 == s2


async def test_read_returns_normalized_metrics_and_persists_settings():
    drv = get_driver("demo")
    ctx = DeviceContext(id="x", external_id="demo-1", timezone=TZ)
    clock.set_now(dt(2026, 10, 22, 9, 0))
    m, raw = await drv.read(ctx)
    for k in ("battery_soc", "battery_voltage", "pv_power", "load_power", "grid_available", "mode", "output_priority"):
        assert k in m
    assert m["mode"] in {"line", "battery"} and 22 < m["battery_voltage"] < 29 and raw["simulated"] is True

    defs = {d.key: d for d in await drv.get_settings(ctx)}
    assert set(defs) == {"output_priority", "charger_priority", "max_ac_charge_current", "buzzer"}
    await drv.write_setting(ctx, "output_priority", "SBU")
    await drv.write_setting(ctx, "max_ac_charge_current", 40)
    await drv.write_setting(ctx, "buzzer", False)
    clock.set_now(dt(2026, 10, 22, 9, 0, 15))
    m2, _ = await drv.read(ctx)
    assert m2["output_priority"] == "SBU"
    cur = {d.key: d.value for d in await drv.get_settings(ctx)}
    assert cur == {"output_priority": "SBU", "charger_priority": "SNU", "max_ac_charge_current": 40, "buzzer": False}


async def test_write_validation():
    drv = get_driver("demo")
    ctx = DeviceContext(id="x", external_id="demo-1", timezone=TZ)
    for key, bad in [("max_ac_charge_current", 70), ("max_ac_charge_current", 5), ("max_ac_charge_current", 25),
                     ("max_ac_charge_current", "abc"), ("output_priority", "XYZ"), ("buzzer", "yes"), ("output_priority", True)]:
        with pytest.raises(ValueError):
            await drv.write_setting(ctx, key, bad)
    with pytest.raises(KeyError):
        await drv.write_setting(ctx, "nope", 1)


async def test_blackout_when_battery_empty_and_recovery():
    drv = get_driver("demo")
    ctx = DeviceContext(id="x", external_id="demo-1", timezone=TZ, state={"soc": 4.0})
    clock.set_now(dt(2026, 10, 22, 22, 0))  # night, grid off
    await drv.read(ctx)
    clock.set_now(dt(2026, 10, 22, 22, 5))
    m, _ = await drv.read(ctx)
    assert m["mode"] == "off" and m["load_power"] == 0
