"""Simulated 24V hybrid off-grid inverter (demo / development / tests).

Deterministic given (state, time): sun curve by local time, load with evening peaks, grid on a rationing schedule
(2h on / 4h off), battery SOC integrating the flows (24V, capacity from the device). Settings are held in `state`
so writes persist. Optional credential `speed` accelerates simulated time (useful for demos).
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app import clock
from app.drivers.base import DeviceContext, Discovered, Driver, SettingDef, clean_metrics
from app.drivers.registry import register

PV_PEAK_W = 1500.0
RATED_VA = 3000.0
INV_EFF = 0.94
GRID_ON_H, GRID_PERIOD_H = 2.0, 6.0

DEFAULT_SETTINGS = {"output_priority": "SUB", "charger_priority": "SNU", "max_ac_charge_current": 30, "buzzer": True}


def _gauss(x: float, mu: float, sigma: float) -> float:
    return math.exp(-((x - mu) ** 2) / (2 * sigma ** 2))


def local_hour(t: datetime, tz: str) -> float:
    lt = t.astimezone(ZoneInfo(tz))
    return lt.hour + lt.minute / 60 + lt.second / 3600


def sun_power(t: datetime, tz: str) -> float:
    h = local_hour(t, tz)
    if h <= 6.0 or h >= 18.0:
        return 0.0
    cloud = 0.88 + 0.12 * math.sin(t.timestamp() / 700.0)
    return PV_PEAK_W * math.sin(math.pi * (h - 6.0) / 12.0) * cloud


def load_demand(t: datetime, tz: str) -> float:
    h = local_hour(t, tz)
    e = t.timestamp()
    w = 300 + 150 * _gauss(h, 7.5, 1.0) + 120 * _gauss(h, 13.5, 1.5) + 420 * _gauss(h, 20.0, 1.8)
    w += 30 * math.sin(e / 97.0) + 20 * math.sin(e / 31.0)
    return min(900.0, max(300.0, w))


def grid_on(t: datetime, phase_h: float = 0.0) -> bool:
    return ((t.timestamp() / 3600.0 + phase_h) % GRID_PERIOD_H) < GRID_ON_H


def battery_voltage(soc: float, bp: float = 0.0) -> float:
    base = 23.0 + 0.055 * soc
    return base + (bp / base) * 0.02


def compute_flows(settings: dict, soc: float, t: datetime, phase: float, tz: str, blackout: bool) -> dict[str, float | str | bool]:
    pv = sun_power(t, tz)
    load = load_demand(t, tz)
    g = grid_on(t, phase)
    out_pri, chg_pri = settings["output_priority"], settings["charger_priority"]
    max_ac_a = float(settings["max_ac_charge_current"])
    v = battery_voltage(soc)

    if g and not (out_pri == "SBU" and soc >= 30.0):
        mode = "line"
    elif blackout:
        mode = "off"
    else:
        mode = "battery"

    pv_to_load = pv_to_batt = ac_chg = grid_w = 0.0
    batt = 0.0
    full = soc >= 100.0
    if mode == "line":
        pv_to_load = min(pv, load) if out_pri == "SUB" else 0.0
        pv_to_batt = 0.0 if full else pv - pv_to_load
        if not full and (chg_pri == "SNU" or (chg_pri == "CSO" and pv_to_batt < 100)):
            ac_chg = max_ac_a * v
        batt = pv_to_batt + ac_chg
        grid_w = load - pv_to_load + ac_chg
        pv = pv_to_load + pv_to_batt
    elif mode == "battery":
        pv_to_load = min(pv, load)
        surplus = 0.0 if full else pv - pv_to_load
        batt = surplus - (load - pv_to_load) / INV_EFF
        pv = pv_to_load + surplus
    else:  # off: nothing served, PV recharges
        load = 0.0
        batt = 0.0 if full else pv
    return {"mode": mode, "pv": pv, "load": load, "grid": grid_w, "batt": batt, "grid_available": g}


def _parse(s: str) -> datetime:
    return datetime.fromisoformat(s)


def advance(state: dict[str, Any], ctx_caps: float, tz: str, now: datetime, speed: float = 1.0) -> dict[str, Any]:
    """Advance the simulation to `now`; mutates state; returns the final flows."""
    st = state
    st.setdefault("settings", dict(DEFAULT_SETTINGS))
    for k, v in DEFAULT_SETTINGS.items():
        st["settings"].setdefault(k, v)
    st.setdefault("soc", 70.0)
    st.setdefault("phase", 0.0)
    st.setdefault("blackout", False)
    st.setdefault("energy", {"day": None, "pv_today": 0.0, "load_today": 0.0, "pv_total": 1234.5})
    if "ts" not in st:
        st["ts"] = now.isoformat()
        st["sim_ts"] = now.isoformat()
    real_prev, sim_prev = _parse(st["ts"]), _parse(st["sim_ts"])
    dt_sim = min(max(0.0, (now - real_prev).total_seconds()) * speed, 12 * 3600.0)
    n = min(720, max(1, math.ceil(dt_sim / 30.0)))
    step = dt_sim / n
    t = sim_prev
    for _ in range(n if dt_sim > 0 else 0):
        t = t + timedelta(seconds=step)
        f = compute_flows(st["settings"], st["soc"], t, st["phase"], tz, st["blackout"])
        st["soc"] = min(100.0, max(0.0, st["soc"] + f["batt"] * step / 3600.0 / ctx_caps * 100.0))
        _update_blackout(st, f)
        e = st["energy"]
        day = t.astimezone(ZoneInfo(tz)).date().isoformat()
        if e["day"] != day:
            e["day"], e["pv_today"], e["load_today"] = day, 0.0, 0.0
        e["pv_today"] += f["pv"] * step / 3.6e6
        e["load_today"] += f["load"] * step / 3.6e6
        e["pv_total"] += f["pv"] * step / 3.6e6
    sim_now = sim_prev + timedelta(seconds=dt_sim)
    if st["energy"]["day"] is None:
        st["energy"]["day"] = sim_now.astimezone(ZoneInfo(tz)).date().isoformat()
    flows = compute_flows(st["settings"], st["soc"], sim_now, st["phase"], tz, st["blackout"])
    st["ts"], st["sim_ts"] = now.isoformat(), sim_now.isoformat()
    flows["sim_now"] = sim_now
    return flows


def _update_blackout(st: dict, f: dict) -> None:
    if not f["grid_available"] and st["soc"] <= 5.0 and f["mode"] == "battery":
        st["blackout"] = True
    elif st["blackout"] and (st["soc"] >= 10.0 or f["grid_available"]):
        st["blackout"] = False


class DemoDriver(Driver):
    code = "demo"
    name = "Demo inverter (simulated 24V hybrid)"
    name_ar = "إنفرتر تجريبي (محاكاة 24 فولت)"
    kind = "inverter"
    poll_interval = 15
    credential_fields: list[dict[str, Any]] = []
    supports_control = True
    supports_discovery = True

    async def discover(self, credentials: dict[str, Any]) -> list[Discovered]:
        return [Discovered(external_id="demo-24v-1", name="Demo Inverter 24V", model="Simulated 24V 3kVA hybrid",
                           serial="DEMO0000000001", meta={"simulated": True})]

    def identify(self, external_id: str) -> tuple[str | None, str | None]:
        return "Simulated 24V 3kVA hybrid", "DEMO-" + external_id[-12:].upper()

    async def read(self, device: DeviceContext) -> tuple[dict[str, Any], dict[str, Any]]:
        speed = float(device.credentials.get("speed") or 1.0)
        now = clock.utcnow()
        f = advance(device.state, device.battery_capacity_wh, device.timezone, now, speed)
        st = device.state
        soc = st["soc"]
        bp = f["batt"]
        v = battery_voltage(soc, bp)
        e = st["energy"]
        ga = f["grid_available"]
        faults = list(st.get("fault_codes") or [])
        mode = "fault" if faults else f["mode"]
        s = st["settings"]
        m = {
            "grid_voltage": 229.0 + 2.0 * math.sin(now.timestamp() / 53.0) if ga else 0.0,
            "grid_frequency": 50.0 if ga else 0.0,
            "grid_power": f["grid"],
            "grid_available": ga,
            "pv_voltage": (95.0 + 20.0 * f["pv"] / PV_PEAK_W) if f["pv"] > 1 else 0.0,
            "pv_current": (f["pv"] / (95.0 + 20.0 * f["pv"] / PV_PEAK_W)) if f["pv"] > 1 else 0.0,
            "pv_power": f["pv"],
            "battery_voltage": v,
            "battery_soc": soc,
            "battery_power": bp,
            "battery_charge_current": max(bp, 0.0) / v,
            "battery_discharge_current": max(-bp, 0.0) / v,
            "load_power": f["load"],
            "load_apparent_power": f["load"] * 1.1,
            "load_percent": f["load"] * 1.1 / RATED_VA * 100.0,
            "output_voltage": 230.0 if f["load"] > 0 or mode != "off" else 0.0,
            "output_frequency": 50.0,
            "bus_voltage": 380.0,
            "inverter_temperature": 32.0 + 12.0 * f["load"] / 900.0 + 6.0 * f["pv"] / PV_PEAK_W,
            "mode": mode,
            "output_priority": s["output_priority"],
            "charger_priority": s["charger_priority"],
            "energy_pv_today": e["pv_today"],
            "energy_pv_total": e["pv_total"],
            "energy_load_today": e["load_today"],
            "fault_codes": faults,
        }
        raw = {"simulated": True, "sim_time": f["sim_now"].astimezone(timezone.utc).isoformat(), "speed": speed,
               "buzzer": s["buzzer"], "max_ac_charge_current": s["max_ac_charge_current"],
               "blackout": st["blackout"]}
        return clean_metrics(m), raw

    async def get_settings(self, device: DeviceContext) -> list[SettingDef]:
        s = {**DEFAULT_SETTINGS, **(device.state.get("settings") or {})}
        return [
            SettingDef("output_priority", "Output source priority", "أولوية مصدر الخرج", "enum", options=[
                {"value": "USB", "label": "Utility first", "label_ar": "الشبكة أولاً"},
                {"value": "SUB", "label": "Solar first", "label_ar": "الشمس أولاً"},
                {"value": "SBU", "label": "Solar, Battery, then Utility", "label_ar": "الشمس ثم البطارية ثم الشبكة"},
            ], value=s["output_priority"], group="output"),
            SettingDef("charger_priority", "Charger source priority", "أولوية مصدر الشحن", "enum", options=[
                {"value": "CSO", "label": "Solar first", "label_ar": "الشمس أولاً"},
                {"value": "SNU", "label": "Solar + Utility", "label_ar": "الشمس + الشبكة"},
                {"value": "OSO", "label": "Solar only", "label_ar": "الشمس فقط"},
            ], value=s["charger_priority"], group="charging"),
            SettingDef("max_ac_charge_current", "Max AC charging current", "أقصى تيار شحن من الشبكة", "number",
                       min=10, max=60, step=10, unit="A", value=s["max_ac_charge_current"], group="charging"),
            SettingDef("buzzer", "Buzzer", "الصافرة", "bool", value=bool(s["buzzer"]), group="general"),
        ]

    async def write_setting(self, device: DeviceContext, key: str, value: Any) -> None:
        defs = {d.key: d for d in await self.get_settings(device)}
        if key not in defs:
            raise KeyError(key)
        device.state.setdefault("settings", dict(DEFAULT_SETTINGS))[key] = defs[key].validate(value)


register(DemoDriver())
