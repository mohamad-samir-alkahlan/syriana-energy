"""Eybond/ShineMonitor driver: signing, parsing, mapping, settings. Fixtures are SHAPED like the real API (see module docs)."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app import clock
from app.drivers import eybond_cloud as eb
from app.drivers.base import DeviceContext, DriverError
from app.drivers.registry import get_driver

FIX = Path(__file__).parent / "fixtures" / "eybond"
BASE = "http://android.shinemonitor.com/public/"
SUFFIX = ("&i18n=en_US&lang=en_US&source=1&_app_client_=android&_app_id_=wifiapp.volfw.watchpower"
          "&_app_version_=1.7.1.0")


def fx(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def sha1(s):
    return hashlib.sha1(s.encode()).hexdigest()


# ------------------------------------------------------------------ signing
def test_login_signature_is_exact():
    salt = "1761127865000"
    url = eb.build_login_url(BASE, "my user@x.com", "P@ss word", salt)
    action = "&action=authSource&usr=my%20user%40x.com&company-key=bnrl_frRFjEz8Mkn" + SUFFIX
    expected_sign = sha1(salt + sha1("P@ss word") + action)
    assert url == f"{BASE}?sign={expected_sign}&salt={salt}{action}"
    assert sha1("P@ss word") == sha1("P@ss word").lower()


def test_call_signature_is_exact():
    salt = "1761127866000"
    url = eb.build_call_url(BASE, "TOK", "SEC", "webQueryDeviceEs", [("page", 0), ("pagesize", 50)], salt)
    action = "&action=webQueryDeviceEs&page=0&pagesize=50" + SUFFIX
    sign = sha1(salt + "SEC" + "TOK" + action)
    assert url == f"{BASE}?sign={sign}&salt={salt}&token=TOK{action}"


# ------------------------------------------------------------------ fake cloud
class FakeCloud:
    def __init__(self, fail_first_n_calls=0, warning=True):
        self.calls: list[dict] = []
        self.logins = 0
        self.fail_n = fail_first_n_calls
        self.written: list[tuple] = []
        self.warning = warning
        self.paging_total = 1
        self.salt_counter = 1761127000000

    def salt(self):
        self.salt_counter += 1
        return str(self.salt_counter)

    def handler(self, request: httpx.Request) -> httpx.Response:
        q = {k: v[0] for k, v in parse_qs(urlparse(str(request.url)).query).items()}
        action = q.get("action")
        self.calls.append(q)
        # verify the signature server-side exactly like the vendor would
        tail = str(request.url).split("&action=", 1)[1]
        raw_action = "&action=" + tail
        if action == "authSource":
            self.logins += 1
            ok = q["sign"] == sha1(q["salt"] + sha1("secret-pass") + raw_action) and q["usr"] == "user@example.com"
            return httpx.Response(200, json=fx("login.json") if ok else fx("login_fail.json"))
        assert q["sign"] == sha1(q["salt"] + "SECRET456def" + "TOKEN123abc" + raw_action), "bad signature"
        assert q["token"] == "TOKEN123abc"
        if self.fail_n > 0:
            self.fail_n -= 1
            return httpx.Response(200, json={"err": 12, "desc": "ERR_TOKEN_EXPIRED", "dat": None})
        if action == "webQueryDeviceEs":
            return httpx.Response(200, json=fx("devices.json"))
        if action == "webQueryDeviceEnergyFlowEs":
            return httpx.Response(200, json=fx("flow.json"))
        if action == "queryDeviceDataOneDayPaging":
            body = fx("paging.json")
            body["dat"]["total"] = self.paging_total
            return httpx.Response(200, json=body)
        if action == "queryDeviceWarning":
            return httpx.Response(200, json=fx("warning.json") if self.warning else {"err": 0, "desc": "ERR_NONE", "dat": {"warning": []}})
        if action == "webQueryDeviceCtrlField":
            return httpx.Response(200, json=fx("ctrlfield.json"))
        if action == "queryDeviceCtrlValue":
            return httpx.Response(200, json={"err": 0, "desc": "ERR_NONE", "dat": {"id": q["id"], "val": fx("ctrlvalue.json")[q["id"]]}})
        if action == "ctrlDevice":
            self.written.append((q["id"], q["val"]))
            return httpx.Response(200, json=fx("ctrl_ok.json"))
        return httpx.Response(200, json={"err": 1, "desc": "ERR_UNKNOWN_ACTION", "dat": None})


@pytest.fixture
def cloud():
    c = FakeCloud()
    drv = get_driver("eybond_cloud")
    drv.transport = httpx.MockTransport(c.handler)
    drv.salt_fn = c.salt
    yield c
    drv.transport = None
    drv.salt_fn = None


CREDS = {"username": "user@example.com", "password": "secret-pass"}
EXT = "W0069062760641:96322507123757:2451:1"


def ctx():
    return DeviceContext(id="d1", external_id=EXT, credentials=CREDS, state={}, timezone="Asia/Damascus")


async def test_discover(cloud):
    found = await get_driver("eybond_cloud").discover(CREDS)
    assert len(found) == 1
    d = found[0]
    assert d.external_id == EXT and d.serial == "96322507123757" and d.name == "Home Inverter"
    assert cloud.logins == 1


async def test_login_failure_raises_driver_error(cloud):
    with pytest.raises(DriverError) as e:
        await get_driver("eybond_cloud").discover({"username": "user@example.com", "password": "wrong"})
    assert e.value.code == "auth_failed" and e.value.err == 258


async def test_read_maps_and_merges(cloud):
    clock.set_now(datetime(2026, 10, 22, 7, 31, tzinfo=timezone.utc))
    c = ctx()
    m, raw = await get_driver("eybond_cloud").read(c)
    assert m["battery_soc"] == 87 and m["battery_voltage"] == 26.8
    assert m["load_power"] == 640.0  # kW -> W from the flow
    assert m["pv_power"] == 1180.0  # kW -> W
    assert m["pv_voltage"] == 142.3 and m["pv_current"] == 8.3
    assert m["grid_voltage"] == 0 and m["grid_available"] is False
    assert m["mode"] == "battery"
    assert m["output_priority"] == "USB"  # "Utility Solar Bat"
    assert m["charger_priority"] == "SNU"  # "Solar + Utility"
    assert m["energy_pv_total"] == pytest.approx(1234.56)  # Wh -> kWh
    assert m["load_percent"] == 21 and m["output_voltage"] == 230.1 and m["output_frequency"] == 50.0
    assert m["load_apparent_power"] == 700 and m["bus_voltage"] == 398
    assert m["inverter_temperature"] == 41
    assert m["battery_charge_current"] == 30 and m["battery_discharge_current"] == 0
    assert m["battery_power"] == pytest.approx(30 * 26.8)  # (charge - discharge) x V
    assert m["fault_codes"] == ["F07: Overload"]  # the 2-day-old warning is ignored
    # unmapped vendor fields stay in raw
    assert raw["day_row"]["Machine Type"] == "Off-Grid"
    assert raw["day_row"]["Solar Feed To Grid Power"] == "0 W"
    assert "energy_flow" in raw
    # all 4 vendor calls went out signed (login + flow + paging + warning)
    actions = [q.get("action") for q in cloud.calls]
    assert actions == ["authSource", "webQueryDeviceEnergyFlowEs", "queryDeviceDataOneDayPaging", "queryDeviceWarning"]
    paging = next(q for q in cloud.calls if q.get("action") == "queryDeviceDataOneDayPaging")
    assert paging["date"] == "2026-10-22" and paging["page"] == "0" and paging["pagesize"] == "1"


def test_map_flow_live_2451_shape():
    from app.drivers.eybond_cloud import map_flow
    m, _ = map_flow({"bt_status": [{"par": "bt_battery_capacity", "val": "86.0000", "unit": "%", "status": 1},
                                   {"par": "battery_active_power", "val": "0", "status": 0}],
                     "pv_status": [{"par": "pv_output_power", "val": "0.0140", "unit": "kW", "status": 1}],
                     "gd_status": [{"par": "grid_active_power", "val": "0.0000", "unit": "V", "status": 0}],
                     "bc_status": [{"par": "load_active_power", "val": "0.5740", "unit": "kW", "status": -1}]})
    assert m == {"battery_soc": 86.0, "pv_power": pytest.approx(14.0), "load_power": pytest.approx(574.0)}


async def test_read_uses_newest_row_of_a_busy_day(cloud):
    # the real cloud returns rows newest first; a day has ~200 rows and the last page is midnight
    cloud.paging_total = 201
    drv = get_driver("eybond_cloud")
    await drv.read(ctx())
    pages = [q["page"] for q in cloud.calls if q.get("action") == "queryDeviceDataOneDayPaging"]
    assert pages == ["0"]


async def test_token_cached_and_relogin_on_error(cloud):
    drv = get_driver("eybond_cloud")
    await drv.discover(CREDS)
    await drv.discover(CREDS)
    assert cloud.logins == 1  # token cached per credential set
    cloud.fail_n = 1  # next authenticated call returns err=12 -> re-login once and retry
    found = await drv.discover(CREDS)
    assert found and cloud.logins == 2


async def test_persistent_error_raises_with_code(cloud):
    cloud.fail_n = 99
    with pytest.raises(DriverError) as e:
        await get_driver("eybond_cloud").discover(CREDS)
    assert e.value.err == 12 and e.value.code == "vendor_error"


async def test_settings_whitelist_ranges_and_values(cloud):
    s = {d.key: d for d in await get_driver("eybond_cloud").get_settings(ctx())}
    assert set(s) == {"output_priority", "charger_priority", "max_ac_charge_current", "buzzer", "battery_cutoff_voltage"}
    assert s["output_priority"].type == "enum" and s["output_priority"].value == "1"
    assert [o["value"] for o in s["charger_priority"].options] == ["0", "1", "2", "3"] and s["charger_priority"].value == "2"
    n = s["max_ac_charge_current"]
    assert (n.type, n.min, n.max, n.value, n.unit) == ("number", 10, 60, 30.0, "A")  # hint 10~60 narrows the safe window
    v = s["battery_cutoff_voltage"]
    assert (v.min, v.max) == (20.0, 24.0)  # safe 24V window is stricter than the device hint 18~26
    with pytest.raises(ValueError):
        v.validate(18.5)
    assert v.validate(22.5) == 22.5
    with pytest.raises(ValueError):
        n.validate(61)
    assert "Restore factory defaults" not in [d.label for d in s.values()]


async def test_write_setting_sends_vendor_id(cloud):
    drv = get_driver("eybond_cloud")
    await drv.write_setting(ctx(), "max_ac_charge_current", 20)
    await drv.write_setting(ctx(), "output_priority", "2")
    assert cloud.written == [("std_max_ac_chg", "20"), ("std_ac_out_pri", "2")]
    with pytest.raises(KeyError):
        await drv.write_setting(ctx(), "factory_reset", 1)


# ------------------------------------------------------------------ pure mapping helpers
def test_unit_conversions_and_title_aliases():
    items = [("AC Output Active Power", "kW", "1.5"), ("Total generation (Wh)".split(" (")[0], "Wh", "2500"),
             ("grid  voltage", "V", "231.5"), ("Battery Capacity", "%", "55"), ("Unknown thing", "", "7")]
    m, raw = eb.map_paging_row(items)
    assert m["load_power"] == 1500 and m["energy_pv_total"] == 2.5 and m["grid_voltage"] == 231.5 and m["battery_soc"] == 55
    assert raw["Unknown thing"] == "7"
    parsed = eb.parse_title_rows([{"title": "Total generation (Wh)", "unit": ""}], ["5000"])
    assert parsed == [("Total generation", "Wh", "5000")]


def test_pv_sum_and_derived_battery_power_without_grid():
    flow = {}
    page = {"pv1_power": 700.0, "pv2_power": 300.0, "pv1_current": 5.0, "pv2_current": 2.0, "pv1_voltage": 140.0,
            "grid_voltage": 0.0, "load_power": 400.0, "mode_text": "Battery Mode"}
    m = eb.combine(flow, page)
    assert m["pv_power"] == 1000 and m["pv_current"] == 7.0 and m["pv_voltage"] == 140.0
    assert m["grid_available"] is False
    assert m["battery_power"] == 600.0  # pv - load, no currents, grid absent


def test_no_battery_power_when_grid_present_and_no_currents():
    m = eb.combine({}, {"pv1_power": 700.0, "grid_voltage": 228.0, "load_power": 400.0, "mode_text": "Line Mode"})
    assert m["grid_available"] is True and m["mode"] == "line" and "battery_power" not in m


def test_text_parsers():
    assert eb.parse_mode("Line Mode") == "line" and eb.parse_mode("Battery Mode") == "battery"
    assert eb.parse_mode("Fault Mode") == "fault" and eb.parse_mode("Standby Mode") == "standby"
    assert eb.parse_mode("Bypass") == "bypass" and eb.parse_mode(None) is None
    assert eb.parse_output_priority("Utility Solar Bat") == "USB"
    assert eb.parse_output_priority("Solar Utility Bat") == "SUB"
    assert eb.parse_output_priority("Solar Bat Utility") == "SBU"
    assert eb.parse_charger_priority("Solar First") == "CSO"
    assert eb.parse_charger_priority("Only Solar") == "OSO"
    assert eb.parse_charger_priority("Solar + Utility") == "SNU"
    assert eb.parse_hint_range("10~60") == (10, 60) and eb.parse_hint_range("0.5 ~ 2.5") == (0.5, 2.5)
    assert eb.parse_hint_range("no range") is None


def test_expiry_parsing():
    assert eb._expiry_to_unix(3600, 1000.0) == 4600.0
    assert eb._expiry_to_unix(1_800_000_000, 1000.0) == 1_800_000_000
    assert eb._expiry_to_unix(1_800_000_000_000, 1000.0) == 1_800_000_000


LIVE_2451_FIELDS = {  # webQueryDeviceCtrlField names from a real devcode 2451 inverter (2026-10-22) -> expected key
    "Output Source Priority": "output_priority", "AC Input Range": "ac_input_range", "Output Voltage": None,
    "Output Frequency": None, "Battery Type": None, "Bulk Charging Voltage": "bulk_charge_voltage",
    "Float Charging Voltage": "float_charge_voltage", "Max. Charging Current": "max_charge_current",
    "Max. AC Charging Current": "max_ac_charge_current", "Charging Source Priority": "charger_priority",
    "Battery Equalization": None, "Real-time Activate Battery Equalization": None,
    "Battery Equalization Time Out": None, "Battery Equalization Time": None, "Equalization Period": None,
    "Equalization Voltage": None, "LCD Auto-return to Main Screen": "lcd_auto_return",
    "Overload Auto Restart": "overload_restart", "Buzzer": "buzzer", "Fault Code Record": None, "Backlight": "backlight",
    "Bypass Function": None, "Solar Feed To Grid": None, "Beeps While Primary Source Interrupt": "primary_source_beep",
    "Over Temperature Auto Restart": "overtemp_restart", "Restore To Default": None,
    "Power Saving Function": "power_saving", "LED Status": None, "LED Brightness": None, "LED Color 1": None,
    "Back to Grid Capacity": "battery_recharge_soc", "Back to Discharge Capacity": "battery_redischarge_soc",
    "Battery Cut-off Capacity": "battery_cutoff_soc", "Battery Capacity to Turn Off AC2": "ac2_off_soc",
    "Discharge Time to Turn Off AC2": None, "Time Interval to Turn On AC2": None, "Time Interval to Turn Off AC2": None,
    "Charge Time to Turn On AC2": None, "Battery Capacity to Turn On AC2": "ac2_on_soc",
}


def test_live_2451_fields_map_to_safe_settings_only():
    from app.drivers.eybond_cloud import match_safe_field
    got = {n: (sf.key if (sf := match_safe_field(n)) else None) for n in LIVE_2451_FIELDS}
    assert got == LIVE_2451_FIELDS
    keys = [k for k in got.values() if k]
    assert len(keys) == len(set(keys))  # one vendor field per setting key


def test_soc_enum_hides_unsafe_options():
    from app.drivers.eybond_cloud import build_setting, match_safe_field
    field = {"name": "Battery Cut-off Capacity", "item": [{"key": "000", "val": "0"}, {"key": "005", "val": "5"},
                                                          {"key": "020", "val": "20"}]}
    sd = build_setting(field, match_safe_field(field["name"]), "020", 24)
    assert [o["value"] for o in sd.options] == ["005", "020"] and sd.value == "020"
