"""Eybond / ShineMonitor cloud driver (WatchPower Wi-Fi, SmartESS, ShineMonitor accounts).

Provenance legend used in comments:
  [VERIFIED]  taken from decompilation of WatchPower Wi-Fi 1.7.1.0 (signing scheme, action names, constants).
  [ASSUMED]   response shapes reconstructed from the spec / typical Eybond payloads. NOT yet checked against the
              live API for the owner's device (SN 96322507123757, datalogger PN W0069062760641). Use
              `python -m app.tools.shinemonitor_probe` to dump real responses and compare with tests/fixtures.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from app import clock
from app.config import settings as app_settings
from app.drivers.base import DeviceContext, Discovered, Driver, DriverError, SettingDef, clean_metrics
from app.drivers.registry import register

log = logging.getLogger(__name__)

COMPANY_KEY = "bnrl_frRFjEz8Mkn"  # [VERIFIED]
SUFFIX = ("&i18n=en_US&lang=en_US&source=1&_app_client_=android"
          "&_app_id_=wifiapp.volfw.watchpower&_app_version_=1.7.1.0")  # [VERIFIED]


# ---------------------------------------------------------------------------------------------------------------
# Signing + HTTP client
# ---------------------------------------------------------------------------------------------------------------
def sha1_hex(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def build_login_url(base: str, username: str, password: str, salt: str) -> str:
    """[VERIFIED] sign = sha1(salt + sha1(password) + action)."""
    pwd = sha1_hex(password)
    action = "&action=authSource&usr=" + quote(username, safe="") + "&company-key=" + COMPANY_KEY + SUFFIX
    sign = sha1_hex(salt + pwd + action)
    return f"{base}?sign={sign}&salt={salt}{action}"


def build_call_url(base: str, token: str, secret: str, name: str, params: list[tuple[str, Any]], salt: str) -> str:
    """[VERIFIED] sign = sha1(salt + secret + token + action)."""
    action = "&action=" + name + "".join(f"&{k}={quote(str(v), safe='')}" for k, v in params) + SUFFIX
    sign = sha1_hex(salt + secret + token + action)
    return f"{base}?sign={sign}&salt={salt}&token={token}{action}"


@dataclass
class _Session:
    token: str
    secret: str
    expires_at: float  # monotonic-independent unix seconds


_SESSIONS: dict[str, _Session] = {}  # cached per credential set until expire


def _expiry_to_unix(expire: Any, now: float) -> float:
    """[ASSUMED] `expire` is seconds-to-live; tolerate epoch seconds / ms too."""
    try:
        x = float(expire)
    except (TypeError, ValueError):
        return now + 3600
    if x > 1e11:
        return x / 1000.0
    if x > 1e9:
        return x
    return now + x


class ShineClient:
    def __init__(self, username: str, password: str, base: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None, salt_fn: Callable[[], str] | None = None):
        self.username = username
        self.password = password
        self.base = base or app_settings.shinemonitor_base
        self.transport = transport
        self._salt = salt_fn or (lambda: str(int(time.time() * 1000)))
        self.trace: list[dict[str, Any]] | None = None  # set to [] by the probe tool to record raw responses
        self._key = sha1_hex(f"{self.base}|{username}|{password}")

    async def _get(self, url: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=httpx.Timeout(15.0)) as c:
                r = await c.get(url)
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise DriverError(f"ShineMonitor request failed: {e.__class__.__name__}: {e}", code="network") from e
        if not isinstance(data, dict):
            raise DriverError("ShineMonitor returned unexpected payload", code="bad_response")
        return data

    async def login(self) -> _Session:
        url = build_login_url(self.base, self.username, self.password, self._salt())
        data = await self._get(url)
        if self.trace is not None:
            self.trace.append({"action": "authSource", "params": {"usr": self.username},
                               "response": _redact(data)})
        if data.get("err") != 0:
            raise DriverError(f"ShineMonitor login failed: err={data.get('err')} {data.get('desc')}",
                              code="auth_failed", err=data.get("err"))
        dat = data.get("dat") or {}
        try:
            sess = _Session(dat["token"], dat["secret"], _expiry_to_unix(dat.get("expire"), time.time()))
        except KeyError as e:
            raise DriverError("ShineMonitor login response missing token/secret", code="bad_response") from e
        _SESSIONS[self._key] = sess
        return sess

    async def _session(self, force: bool = False) -> _Session:
        s = _SESSIONS.get(self._key)
        if force or s is None or s.expires_at - 30 <= time.time():
            return await self.login()
        return s

    async def call(self, name: str, **params: Any) -> Any:
        """Authenticated call. err != 0 -> re-login once and retry, then raise DriverError(err)."""
        plist = list(params.items())
        last: dict[str, Any] = {}
        for attempt in (0, 1):
            sess = await self._session(force=attempt == 1)
            url = build_call_url(self.base, sess.token, sess.secret, name, plist, self._salt())
            last = await self._get(url)
            if self.trace is not None:
                self.trace.append({"action": name, "params": params, "response": _redact(last)})
            if last.get("err") == 0:
                return last.get("dat")
        raise DriverError(f"ShineMonitor error {last.get('err')} ({last.get('desc')}) on {name}",
                          code="vendor_error", err=last.get("err"))


def _redact(d: Any) -> Any:
    if isinstance(d, dict):
        return {k: ("***" if k in ("token", "secret") else _redact(v)) for k, v in d.items()}
    if isinstance(d, list):
        return [_redact(x) for x in d]
    return d


# ---------------------------------------------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------------------------------------------
_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def to_number(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = _NUM.search(str(v).replace(",", ""))
    return float(m.group()) if m else None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _split_unit(title: str, unit: str | None) -> tuple[str, str]:
    m = re.search(r"\(([^)]*)\)\s*$", title)
    if m:
        return title[:m.start()].strip(), (unit or m.group(1)).strip()
    return title.strip(), (unit or "").strip()


# kind -> unit conversion family
POWER, ENERGY, VOLT, CURR, OTHER = "power", "energy", "volt", "curr", "other"

# Tolerant alias table keyed by normalized title (lowercase, alphanumerics only).  [ASSUMED] for names not in the
# spec's "seen on the real device" list; the spec list is [VERIFIED by owner report].
TITLE_ALIASES: dict[str, tuple[str, str]] = {
    "gridvoltage": ("grid_voltage", VOLT), "acinputvoltage": ("grid_voltage", VOLT),
    "utilityvoltage": ("grid_voltage", VOLT), "mainsvoltage": ("grid_voltage", VOLT),
    "gridfrequency": ("grid_frequency", OTHER), "acinputfrequency": ("grid_frequency", OTHER),
    "utilityfrequency": ("grid_frequency", OTHER),
    "pv1inputvoltage": ("pv1_voltage", VOLT), "pvinputvoltage": ("pv1_voltage", VOLT), "pv1voltage": ("pv1_voltage", VOLT),
    "pv2inputvoltage": ("pv2_voltage", VOLT), "pv2voltage": ("pv2_voltage", VOLT),
    "pv1chargingpower": ("pv1_power", POWER), "pv1inputpower": ("pv1_power", POWER),
    "pvchargingpower": ("pv1_power", POWER), "pvinputpower": ("pv1_power", POWER), "pv1power": ("pv1_power", POWER),
    "pv2chargingpower": ("pv2_power", POWER), "pv2inputpower": ("pv2_power", POWER), "pv2power": ("pv2_power", POWER),
    "pv1inputcurrent": ("pv1_current", CURR), "pvinputcurrent": ("pv1_current", CURR), "pv1current": ("pv1_current", CURR),
    "pv2inputcurrent": ("pv2_current", CURR), "pv2current": ("pv2_current", CURR),
    "batteryvoltage": ("battery_voltage", VOLT),
    "batterycapacity": ("battery_soc", OTHER), "batterysoc": ("battery_soc", OTHER),
    "batterystateofcharge": ("battery_soc", OTHER),
    "busvoltage": ("bus_voltage", VOLT),
    "acoutputvoltage": ("output_voltage", VOLT), "outputvoltage": ("output_voltage", VOLT),
    "acoutputfrequency": ("output_frequency", OTHER), "outputfrequency": ("output_frequency", OTHER),
    "acoutputactivepower": ("load_power", POWER), "outputactivepower": ("load_power", POWER),
    "outputpower": ("load_power", POWER), "loadpower": ("load_power", POWER),
    "acoutputapparentpower": ("load_apparent_power", POWER), "outputapparentpower": ("load_apparent_power", POWER),
    "outputloadpercent": ("load_percent", OTHER), "loadpercent": ("load_percent", OTHER),
    "outputloadpercentage": ("load_percent", OTHER),
    "batterychargingcurrent": ("battery_charge_current", CURR),
    "batterydischargecurrent": ("battery_discharge_current", CURR),
    "batterydischargingcurrent": ("battery_discharge_current", CURR),
    "inverterheatsinktemperature": ("inverter_temperature", OTHER), "heatsinktemperature": ("inverter_temperature", OTHER),
    "invertertemperature": ("inverter_temperature", OTHER),
    "model": ("mode_text", OTHER), "workmode": ("mode_text", OTHER), "workingmode": ("mode_text", OTHER),
    "outputsourcepriority": ("output_priority_text", OTHER), "outputpriority": ("output_priority_text", OTHER),
    "chargersourcepriority": ("charger_priority_text", OTHER), "chargerpriority": ("charger_priority_text", OTHER),
    "totalgeneration": ("energy_pv_total", ENERGY), "totalenergy": ("energy_pv_total", ENERGY),
    "todaygeneration": ("energy_pv_today", ENERGY), "dailygeneration": ("energy_pv_today", ENERGY),
    "todayenergy": ("energy_pv_today", ENERGY), "dailyenergy": ("energy_pv_today", ENERGY),
    "dailyloadenergy": ("energy_load_today", ENERGY), "todayloadenergy": ("energy_load_today", ENERGY),
}
DEFAULT_UNIT = {POWER: "W", ENERGY: "Wh"}  # when the title carries no unit (e.g. "Total generation")


def convert(kind: str, value: float, unit: str) -> float:
    u = unit.strip().lower()
    if kind == POWER:
        return value * 1000.0 if u == "kw" else value * 1e6 if u == "mw" else value
    if kind == ENERGY:
        u = u or "wh"
        return {"wh": value / 1000.0, "kwh": value, "mwh": value * 1000.0, "kw·h": value}.get(u, value / 1000.0)
    if kind == VOLT:
        return value / 1000.0 if u == "mv" else value
    if kind == CURR:
        return value / 1000.0 if u == "ma" else value
    return value


def parse_mode(text: str | None) -> str | None:
    if not text:
        return None
    t = text.lower()
    if "fault" in t or "error" in t:
        return "fault"
    if "bypass" in t:
        return "bypass"
    if "line" in t or "utility" in t or "grid" in t or "mains" in t:
        return "line"
    if "batt" in t or "inverter" in t:
        return "battery"
    if "standby" in t or "stand-by" in t or "idle" in t or "power saving" in t:
        return "standby"
    if "shutdown" in t or "power off" in t or t.strip() == "off":
        return "off"
    return "unknown"


def parse_output_priority(text: str | None) -> str | None:
    """'Utility Solar Bat' -> 'USB', 'Solar Utility Bat' -> 'SUB', 'Solar Bat Utility' -> 'SBU'."""
    if not text:
        return None
    letters = []
    for w in re.findall(r"[a-zA-Z]+", text.lower()):
        if w.startswith(("util", "grid", "mains")):
            letters.append("U")
        elif w.startswith("sol") or w == "pv":
            letters.append("S")
        elif w.startswith("bat"):
            letters.append("B")
    if len(letters) == 3 and set(letters) == {"U", "S", "B"}:
        return "".join(letters)
    return text.strip() if text.strip() in ("USB", "SUB", "SBU") else text.strip()


def parse_charger_priority(text: str | None) -> str | None:
    """Voltronic codes: CUT utility first, CSO solar first, SNU solar+utility, OSO only solar."""
    if not text:
        return None
    t = text.lower()
    if re.search(r"only\s*solar|solar\s*only", t):
        return "OSO"
    if re.search(r"solar\s*(\+|and|&)\s*util|util\w*\s*(\+|and|&)\s*solar", t):
        return "SNU"
    if "solar first" in t or "solar priority" in t:
        return "CSO"
    if "utility first" in t or "utility priority" in t:
        return "CUT"
    return text.strip()


def parse_title_rows(titles: list[dict[str, Any]], fields: list[Any]) -> list[tuple[str, str, Any]]:
    out = []
    for i, t in enumerate(titles or []):
        if i >= len(fields):
            break
        name, unit = _split_unit(str(t.get("title", "")), t.get("unit"))
        out.append((name, unit, fields[i]))
    return out


def map_paging_row(items: list[tuple[str, str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Map (title, unit, value) triples -> (partial metrics incl. *_text helpers, raw)."""
    m: dict[str, Any] = {}
    raw: dict[str, Any] = {}
    for name, unit, val in items:
        raw[name] = val if not unit else f"{val} {unit}"
        hit = TITLE_ALIASES.get(_norm(name))
        if not hit:
            continue
        key, kind = hit
        if key in ("mode_text", "output_priority_text", "charger_priority_text"):
            if val not in (None, ""):
                m[key] = str(val)
            continue
        num = to_number(val)
        if num is None:
            continue
        m[key] = convert(kind, num, unit or DEFAULT_UNIT.get(kind, ""))
    return m, raw


FLOW_PARS: dict[str, tuple[str, str]] = {
    "bt_battery_capacity": ("battery_soc", OTHER), "bt_cap": ("battery_soc", OTHER),
    "bt_voltage": ("battery_voltage", VOLT), "bt_vol": ("battery_voltage", VOLT),
    "bc_pow": ("load_power", POWER), "bc_per": ("load_percent", OTHER), "bc_vol": ("output_voltage", VOLT),
    "gd_vol": ("grid_voltage", VOLT), "gd_fre": ("grid_frequency", OTHER),
    "pv_pow": ("pv_power", POWER), "pv_vol": ("pv_voltage", VOLT),
    # [VERIFIED 2026-10-22, live devcode 2451] names the cloud actually sends (values in kW)
    "pv_output_power": ("pv_power", POWER), "load_active_power": ("load_power", POWER),
}


def map_flow(dat: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """[ASSUMED shape] dat has lists bt_status/bc_status/gd_status/pv_status of {par,status,unit,val}."""
    m: dict[str, Any] = {}
    raw: dict[str, Any] = {}
    for lst in ("bt_status", "bc_status", "gd_status", "pv_status"):
        for it in (dat.get(lst) or []):
            par = str(it.get("par", ""))
            val, unit = it.get("val"), str(it.get("unit") or "")
            raw[par] = {"val": val, "unit": unit, "status": it.get("status")}
            if par in ("bc_model", "model"):
                if val not in (None, ""):
                    m["mode_text"] = str(val)
                continue
            hit = FLOW_PARS.get(par)
            if not hit:
                continue
            num = to_number(val)
            if num is not None:
                m[hit[0]] = convert(hit[1], num, unit or DEFAULT_UNIT.get(hit[1], ""))
    return m, raw


def combine(flow: dict[str, Any], page: dict[str, Any]) -> dict[str, Any]:
    """Merge: realtime flow wins where both have a value; the paging row fills the rest. Then derive."""
    p = dict(page)
    f = dict(flow)
    m: dict[str, Any] = {**p, **{k: v for k, v in f.items() if v is not None}}
    # PV: sum PV1 + PV2
    pv_pows = [p.get(k) for k in ("pv1_power", "pv2_power") if p.get(k) is not None]
    if "pv_power" not in m and pv_pows:
        m["pv_power"] = sum(pv_pows)
    pv_curs = [p.get(k) for k in ("pv1_current", "pv2_current") if p.get(k) is not None]
    if pv_curs:
        m["pv_current"] = sum(pv_curs)
    if "pv_voltage" not in m:
        for k in ("pv1_voltage", "pv2_voltage"):
            if p.get(k) is not None:
                m["pv_voltage"] = p[k]
                break
    # mode / priorities
    mode = parse_mode(m.pop("mode_text", None))
    if mode:
        m["mode"] = mode
    if "output_priority_text" in m:
        m["output_priority"] = parse_output_priority(m.pop("output_priority_text"))
    if "charger_priority_text" in m:
        m["charger_priority"] = parse_charger_priority(m.pop("charger_priority_text"))
    # grid availability
    gv = m.get("grid_voltage")
    if gv is not None:
        m["grid_available"] = gv >= 80.0
    elif m.get("mode") in ("line", "bypass"):
        m["grid_available"] = True
    # battery power (+ charging / - discharging)
    chg, dis, bv = m.get("battery_charge_current"), m.get("battery_discharge_current"), m.get("battery_voltage")
    if (chg is not None or dis is not None) and bv is not None:
        m["battery_power"] = ((chg or 0.0) - (dis or 0.0)) * bv
    elif m.get("grid_available") is False and m.get("pv_power") is not None and m.get("load_power") is not None:
        m["battery_power"] = m["pv_power"] - m["load_power"]  # derived: no grid => battery covers the balance
    return m


def parse_warnings(dat: Any, now: datetime, max_age: timedelta = timedelta(minutes=15)) -> list[str]:
    """[ASSUMED shape] dat.warning[] with code/desc/gts; we keep recent, unhandled entries as fault codes."""
    items: list[Any] = []
    if isinstance(dat, dict):
        items = dat.get("warning") or dat.get("warnings") or dat.get("row") or []
    elif isinstance(dat, list):
        items = dat
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if str(it.get("handle", "")).lower() in ("1", "true", "handled"):
            continue
        ts = it.get("gts") or it.get("time") or it.get("gtime")
        if ts:
            try:
                t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                if now - t > max_age:
                    continue
            except ValueError:
                pass
        code = str(it.get("code") or it.get("id") or "").strip()
        desc = str(it.get("desc") or it.get("descen") or it.get("name") or "").strip()
        label = ": ".join(x for x in (code, desc) if x)
        if label:
            out.append(label)
    return out


# ---------------------------------------------------------------------------------------------------------------
# Control fields (settings). Whitelist = only settings we know how to validate safely.  [ASSUMED] vendor names.
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class SafeField:
    pattern: str
    key: str
    label: str
    label_ar: str
    group: str
    unit: str | None = None
    # (min, max, step) for a 24V system; voltage ranges are scaled by nominal/24
    safe: tuple[float, float, float] | None = None
    scale_with_voltage: bool = False


SAFE_FIELDS: list[SafeField] = [
    SafeField(r"output\s*source\s*priority|output\s*priority", "output_priority", "Output source priority",
              "أولوية مصدر الخرج", "output"),
    SafeField(r"charger\s*source\s*priority|charge\w*\s*priority", "charger_priority", "Charger source priority",
              "أولوية مصدر الشحن", "charging"),
    SafeField(r"max\w*\.?\s*(ac|utility|grid|mains)\s*charg\w*\s*current", "max_ac_charge_current",
              "Max AC charging current", "أقصى تيار شحن من الشبكة", "charging", "A", (2, 60, 1)),
    SafeField(r"^max\w*\.?\s*charg\w*\s*current", "max_charge_current", "Max charging current",
              "أقصى تيار شحن", "charging", "A", (2, 120, 1)),
    SafeField(r"buzzer|alarm\s*control|beeps?", "buzzer", "Buzzer", "الصافرة", "general"),
    SafeField(r"(battery\s*)?cut.?off\s*voltage|low\s*dc\s*cut.?off", "battery_cutoff_voltage", "Battery cut-off voltage",
              "جهد قطع البطارية", "battery", "V", (20.0, 24.0, 0.1), True),
    SafeField(r"bulk\s*charg\w*\s*voltage|constant\s*voltage|cv\s*charg\w*\s*voltage", "bulk_charge_voltage",
              "Bulk charging voltage", "جهد الشحن الأساسي", "battery", "V", (27.0, 29.2, 0.1), True),
    SafeField(r"float\s*charg\w*\s*voltage", "float_charge_voltage", "Float charging voltage", "جهد الشحن العائم",
              "battery", "V", (26.0, 28.0, 0.1), True),
    SafeField(r"re.?charge\s*voltage|back\s*to\s*(utility|grid)\s*voltage", "battery_recharge_voltage",
              "Battery re-charge voltage", "جهد العودة للشبكة", "battery", "V", (22.0, 25.5, 0.1), True),
    SafeField(r"re.?discharge\s*voltage|back\s*to\s*(battery|discharge)\s*voltage", "battery_redischarge_voltage",
              "Battery re-discharge voltage", "جهد العودة للبطارية", "battery", "V", (24.0, 29.0, 0.1), True),
]

_RANGE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:~|–|—|to|…|\.\.)\s*(-?\d+(?:\.\d+)?)", re.I)
_RANGE_DASH = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)")


def parse_hint_range(hint: str | None) -> tuple[float, float] | None:
    if not hint:
        return None
    m = _RANGE.search(hint) or _RANGE_DASH.search(hint)
    if not m:
        return None
    lo, hi = float(m.group(1)), float(m.group(2))
    return (lo, hi) if lo <= hi else (hi, lo)


def match_safe_field(name: str) -> SafeField | None:
    n = name.strip().lower()
    for sf in SAFE_FIELDS:
        if re.search(sf.pattern, n):
            return sf
    return None


def nominal_system_voltage(battery_voltage: float | None) -> int:
    if battery_voltage is None:
        return 24
    return 48 if battery_voltage >= 40 else 24 if battery_voltage >= 20 else 12


def build_setting(field: dict[str, Any], sf: SafeField, current: Any, nominal_v: int) -> SettingDef | None:
    items = field.get("item") or []
    name = sf.key
    unit = sf.unit or (field.get("unit") or None)
    if items:  # enum
        opts = []
        for it in items:
            key, label = str(it.get("key")), str(it.get("val", it.get("key")))
            opts.append({"value": key, "label": label, "label_ar": label})
        val = None
        if current is not None:
            cs = str(current)
            val = next((o["value"] for o in opts if o["value"] == cs), None) \
                or next((o["value"] for o in opts if o["label"].lower() == cs.lower()), None)
        # buzzer-like two-option enums stay enums: vendor keys are opaque ids we must echo back verbatim
        return SettingDef(sf.key, sf.label, sf.label_ar, "enum", options=opts, value=val, group=sf.group)
    if sf.safe is None:
        return None  # numeric field with no known safe window -> not exposed
    lo, hi, step = sf.safe
    if sf.scale_with_voltage:
        k = nominal_v / 24.0
        lo, hi = round(lo * k, 2), round(hi * k, 2)
    rng = parse_hint_range(field.get("hint"))
    if rng:  # never wider than what the device itself accepts
        lo, hi = max(lo, rng[0]), min(hi, rng[1])
    if lo > hi:
        return None
    num = to_number(current)
    return SettingDef(name, sf.label, sf.label_ar, "number", min=lo, max=hi, step=step, unit=unit, value=num,
                      group=sf.group)


def parse_external_id(external_id: str) -> tuple[str, str, str, str]:
    parts = external_id.split(":")
    if len(parts) != 4:
        raise DriverError(f"Bad eybond external_id: {external_id}", code="bad_external_id")
    return parts[0], parts[1], parts[2], parts[3]  # pn, sn, devcode, devaddr


# ---------------------------------------------------------------------------------------------------------------
class EybondCloudDriver(Driver):
    code = "eybond_cloud"
    name = "WatchPower / SmartESS / ShineMonitor (cloud account)"
    name_ar = "WatchPower / SmartESS / ShineMonitor (حساب سحابي)"
    kind = "inverter"
    poll_interval = 60
    credential_fields = [
        {"key": "username", "label": "Username", "label_ar": "اسم المستخدم", "type": "text", "required": True},
        {"key": "password", "label": "Password", "label_ar": "كلمة السر", "type": "password", "required": True},
    ]
    supports_control = True
    supports_discovery = True
    transport: httpx.AsyncBaseTransport | None = None  # tests inject httpx.MockTransport
    salt_fn: Callable[[], str] | None = None

    def client(self, credentials: dict[str, Any]) -> ShineClient:
        u, p = credentials.get("username"), credentials.get("password")
        if not u or not p:
            raise DriverError("username and password are required", code="bad_credentials")
        return ShineClient(u, p, transport=self.transport, salt_fn=self.salt_fn)

    def identify(self, external_id: str) -> tuple[str | None, str | None]:
        try:
            pn, sn, devcode, _ = parse_external_id(external_id)
        except DriverError:
            return None, None
        return f"Eybond inverter (devcode {devcode})", sn

    async def discover(self, credentials: dict[str, Any]) -> list[Discovered]:
        c = self.client(credentials)
        dat = await c.call("webQueryDeviceEs", page=0, pagesize=50)  # [VERIFIED action]; shape [ASSUMED]
        out = []
        for d in (dat or {}).get("device", []) or []:
            pn, sn, devcode, devaddr = (str(d.get(k, "")) for k in ("pn", "sn", "devcode", "devaddr"))
            out.append(Discovered(
                external_id=f"{pn}:{sn}:{devcode}:{devaddr}",
                name=str(d.get("alias") or sn or pn),
                model=f"Eybond inverter (devcode {devcode})", serial=sn,
                meta={"pn": pn, "devcode": devcode, "devaddr": devaddr, "status": d.get("status")}))
        return out

    async def read(self, device: DeviceContext) -> tuple[dict[str, Any], dict[str, Any]]:
        c = self.client(device.credentials)
        pn, sn, devcode, devaddr = parse_external_id(device.external_id)
        now = clock.utcnow()
        local_date = now.astimezone(ZoneInfo(device.timezone)).date().isoformat()
        raw: dict[str, Any] = {}
        flow_m: dict[str, Any] = {}
        page_m: dict[str, Any] = {}
        errors: list[str] = []

        try:
            dat = await c.call("webQueryDeviceEnergyFlowEs", pn=pn, sn=sn, devaddr=devaddr, devcode=devcode)
            flow_m, flow_raw = map_flow(dat or {})
            raw["energy_flow"] = flow_raw
        except DriverError as e:
            errors.append(f"flow: {e.message}")

        try:
            # [VERIFIED 2026-10-22 on a live 2451 inverter] rows come newest first: page 0 is the latest
            # record (~5 min old) and the last page is the first record after midnight.
            page = await c.call("queryDeviceDataOneDayPaging", pn=pn, devcode=devcode, sn=sn, devaddr=devaddr,
                                page=0, pagesize=1, date=local_date)
            rows = (page or {}).get("row") or []
            if rows:
                items = parse_title_rows(page.get("title") or [], rows[0].get("field") or [])
                page_m, page_raw = map_paging_row(items)
                raw["day_row"] = page_raw
        except DriverError as e:
            errors.append(f"paging: {e.message}")

        if not flow_m and not page_m:
            raise DriverError("; ".join(errors) or "no data returned", code="no_data")

        metrics = combine(flow_m, page_m)

        # vendor warnings -> fault_codes (rate-limited to once / 5 min via device.state)
        last_warn = float(device.state.get("warn_ts") or 0)
        faults: list[str] = device.state.get("faults") or []
        if time.time() - last_warn > 300:
            try:
                wdat = await c.call("queryDeviceWarning", pn=pn, devcode=devcode, devaddr=devaddr, sn=sn,
                                    page=0, pagesize=10, mode="strict")
                faults = parse_warnings(wdat, now)
                raw["warnings"] = wdat
            except DriverError as e:
                errors.append(f"warning: {e.message}")
            device.state["warn_ts"] = time.time()
            device.state["faults"] = faults
        if faults:
            metrics["fault_codes"] = faults
        if metrics.get("battery_voltage"):
            device.state["nominal_v"] = nominal_system_voltage(metrics["battery_voltage"])
        if errors:
            raw["partial_errors"] = errors
        return clean_metrics(metrics), raw

    async def _fields(self, c: ShineClient, pn: str, sn: str, devcode: str, devaddr: str) -> list[dict[str, Any]]:
        dat = await c.call("webQueryDeviceCtrlField", pn=pn, sn=sn, devcode=devcode, devaddr=devaddr)
        return list((dat or {}).get("field") or [])

    async def _current(self, c: ShineClient, pn, sn, devcode, devaddr, fid) -> Any:
        try:
            dat = await c.call("queryDeviceCtrlValue", pn=pn, sn=sn, devcode=devcode, devaddr=devaddr, id=fid)
            return (dat or {}).get("val")
        except DriverError as e:
            log.warning("queryDeviceCtrlValue %s failed: %s", fid, e.message)
            return None

    async def get_settings(self, device: DeviceContext) -> list[SettingDef]:
        c = self.client(device.credentials)
        pn, sn, devcode, devaddr = parse_external_id(device.external_id)
        fields = await self._fields(c, pn, sn, devcode, devaddr)
        picked: list[tuple[dict[str, Any], SafeField]] = []
        seen: set[str] = set()
        for f in fields:
            sf = match_safe_field(str(f.get("name", "")))
            if sf and sf.key not in seen:
                seen.add(sf.key)
                picked.append((f, sf))
        sem = asyncio.Semaphore(4)

        async def cur(f):
            async with sem:
                return await self._current(c, pn, sn, devcode, devaddr, f.get("id"))

        values = await asyncio.gather(*(cur(f) for f, _ in picked))
        nominal = int(device.state.get("nominal_v") or 24)
        out = []
        for (f, sf), v in zip(picked, values):
            sd = build_setting(f, sf, v, nominal)
            if sd:
                out.append(sd)
        return out

    async def write_setting(self, device: DeviceContext, key: str, value: Any) -> None:
        c = self.client(device.credentials)
        pn, sn, devcode, devaddr = parse_external_id(device.external_id)
        fields = await self._fields(c, pn, sn, devcode, devaddr)
        for f in fields:
            sf = match_safe_field(str(f.get("name", "")))
            if sf and sf.key == key:
                val = value if not isinstance(value, bool) else ("1" if value else "0")
                await c.call("ctrlDevice", pn=pn, devcode=devcode, devaddr=devaddr, sn=sn, id=f.get("id"), val=val)
                return
        raise KeyError(key)


register(EybondCloudDriver())
