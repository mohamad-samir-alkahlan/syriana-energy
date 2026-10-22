"""UI end-to-end tests against the real stack (frontend :3000 -> backend). Run for ar/en x desktop/mobile."""
from __future__ import annotations

import re
import time

import pyotp
import requests
from playwright.sync_api import expect

from conftest import ADMIN, DEMO, PW, WEB, Api, admin_api, make_user, uniq_email


def logout(ui, name):
    p = ui.page
    if ui.vp == "mobile":
        p.get_by_label(ui.t("nav.more")).click()
        p.get_by_role("dialog").get_by_role("button", name=ui.t("common.logout")).click()
    else:
        p.get_by_label(name, exact=True).click()
        p.get_by_role("menuitem", name=ui.t("common.logout")).click()
    p.wait_for_url(re.compile(r"/(ar|en)(/login)?/?$"), timeout=15000)


def nav_to(ui, key, href):
    """Use real navigation chrome (sidebar on desktop, bottom bar / More sheet on mobile)."""
    p = ui.page
    label = ui.t(f"nav.{key}")
    nav = p.get_by_role("navigation", name=ui.t("nav.main"))
    if nav.count() and nav.first.is_visible():
        link = nav.first.get_by_role("link", name=label)
        if link.count():
            link.first.click()
            p.wait_for_url(re.compile(re.escape(href)))
            return
    p.get_by_label(ui.t("nav.more")).click()
    p.get_by_role("dialog").get_by_role("link", name=label).click()
    p.wait_for_url(re.compile(re.escape(href)))


# ------------------------------------------------------------------ public
def test_landing_and_pricing_loads_plans(ui):
    ui.goto("")
    plans = requests.get(f"{WEB}/api/public/plans").json()
    assert len(plans) >= 4
    body = ui.page.locator("body")
    for pl in plans:
        name = pl["name_ar"] if ui.loc == "ar" else pl["name"]
        expect(body).to_contain_text(name)
    expect(ui.page.get_by_text(ui.t("landing.title"))).to_be_visible()
    ui.assert_no_raw_keys()
    ui.no_h_overflow()
    html_dir = ui.page.evaluate("document.documentElement.dir")
    assert html_dir == ("rtl" if ui.loc == "ar" else "ltr")
    ui.shot("landing")
    # login/register pages render
    ui.goto("/login"); ui.no_h_overflow(); ui.shot("login")
    ui.goto("/register"); ui.no_h_overflow()


# ------------------------------------------------------------------ onboarding
def test_register_empty_state_demo_logout_login(ui):
    p = ui.page
    email = uniq_email("reg")
    ui.goto("/register")
    p.get_by_label(ui.t("auth.name")).fill("Reg Tester")
    p.get_by_label(ui.t("auth.tenant_name")).fill("Reg Home")
    p.get_by_label(ui.t("auth.email")).fill(email)
    p.get_by_label(ui.t("auth.password"), exact=True).fill(PW)
    p.locator("button[type=submit]").click()
    p.wait_for_url(re.compile(r"/app/?$"), timeout=20000)
    expect(p.get_by_text(ui.t("empty.title"))).to_be_visible()
    ui.no_h_overflow(); ui.shot("empty-state")
    p.get_by_role("button", name=ui.t("empty.try_demo")).click()
    expect(ui.toast(ui.t("empty.demo_added"))).to_be_visible()
    # dashboard now shows live data
    expect(p.get_by_text(ui.t("dash.now"), exact=True)).to_be_visible()
    expect(p.get_by_text(ui.t("dash.stat_pv"))).to_be_visible()
    # logout then login again
    logout(ui, "Reg Tester")
    ui.login(email, PW)
    expect(p.get_by_text(ui.t("dash.now"), exact=True)).to_be_visible()
    # wrong password shows an error, stays on login
    logout(ui, "Reg Tester")
    ui.goto("/login")
    p.get_by_label(ui.t("auth.email")).fill(email)
    p.get_by_label(ui.t("auth.password"), exact=True).fill("wrong-password-1")
    p.locator("button[type=submit]").click()
    expect(p.locator("[role=alert]").first).to_be_visible()
    assert "/login" in p.url


# ------------------------------------------------------------------ dashboard
def test_demo_dashboard_live(ui):
    p = ui.page
    ui.login(*DEMO)
    for k in ["dash.stat_pv", "dash.stat_load", "dash.stat_runtime", "dash.stat_total", "dash.chart_title", "dash.alerts"]:
        expect(p.locator("main").get_by_text(ui.t(k)).first).to_be_visible()
    expect(p.get_by_text(ui.t("dash.last_update")).first).to_be_visible()
    # chart rendered with real paths
    assert p.locator("svg path").count() > 10
    # alerts card has entries (seed generated grid lost/restored)
    expect(p.get_by_text(ui.t("dash.no_alerts"))).to_have_count(0)
    # live polling: count /live responses and check the readings change after the 15s poll
    lives = []
    p.on("response", lambda r: lives.append(r) if "/live" in r.url and r.status == 200 else None)

    def snapshot():
        return p.evaluate("""() => { const s=document.querySelector('main svg'); return s ? s.textContent : '' }""")
    before = snapshot()
    stat_before = p.locator("main").inner_text()
    p.wait_for_timeout(33000)
    assert len(lives) >= 2, f"expected >=2 polls in 33s, got {len(lives)}"
    after = snapshot()
    assert before != after or stat_before != p.locator("main").inner_text(), "live values never changed across polls"
    ui.no_h_overflow(); ui.assert_no_raw_keys()
    ui.shot("dashboard")


def test_nav_pages_render_without_errors(ui):
    ui.login(*DEMO)
    for key, href in [("history", "/app/history"), ("control", "/app/control"), ("alerts", "/app/alerts"), ("devices", "/app/devices"), ("dashboard", "/app")]:
        if key == "devices" and ui.vp == "mobile":
            nav_to(ui, "devices", href)  # via More
        else:
            nav_to(ui, key, href)
        ui.page.wait_for_load_state("networkidle")
        ui.no_h_overflow(); ui.assert_no_raw_keys()


# ------------------------------------------------------------------ history
def test_history_presets_and_csv(ui):
    p = ui.page
    ui.login(*DEMO)
    ui.goto("/app/history")
    expect(p.get_by_text(ui.t("history.power_chart"))).to_be_visible()
    grp = p.get_by_role("radiogroup", name=ui.t("history.range"))
    for k in ["history.d7", "history.d30", "history.today"]:
        grp.get_by_role("radio", name=ui.t(k)).click()
        p.wait_for_load_state("networkidle")
        expect(p.get_by_text(ui.t("history.power_chart"))).to_be_visible()
    grp.get_by_role("radio", name=ui.t("history.custom")).click()
    expect(p.get_by_label(ui.t("history.from"))).to_be_visible()
    grp.get_by_role("radio", name=ui.t("history.today")).click()
    p.wait_for_timeout(800)
    with p.expect_download() as dl:
        p.get_by_role("button", name=ui.t("history.export_power")).first.click()
    path = dl.value.path()
    txt = open(path, encoding="utf-8-sig").read().strip().splitlines()
    assert dl.value.suggested_filename.endswith(".csv")
    assert len(txt) > 5, f"CSV has only {len(txt)} lines"
    assert "," in txt[0]
    grp.get_by_role("radio", name=ui.t("history.d7")).click()
    p.wait_for_timeout(1000)
    ui.no_h_overflow()
    ui.shot("history")


# ------------------------------------------------------------------ control
def test_control_change_priority_and_persist(ui):
    p = ui.page
    ui.login(*DEMO)
    ui.goto("/app/control")
    expect(p.get_by_text(ui.t("control.title")).first).to_be_visible()
    # pick the output-priority radiogroup via API labels
    me = Api(); me.login(*DEMO)
    dev = me.req("GET", "/api/devices").json()[0]["id"]
    st = {s["key"]: s for s in me.req("GET", f"/api/devices/{dev}/settings").json()}["output_priority"]
    label = st["label_ar"] if ui.loc == "ar" else st["label"]
    grp = p.get_by_role("radiogroup", name=label)
    cur = st["value"]
    target = next(o for o in st["options"] if o["value"] != cur)
    tl = target["label_ar"] if ui.loc == "ar" else target["label"]
    grp.get_by_role("radio", name=tl, exact=True).click()
    dlg = p.get_by_role("dialog")
    expect(dlg).to_be_visible()
    expect(dlg).to_contain_text(ui.t("control.confirm_title"))
    ui.shot("control-confirm")
    dlg.get_by_role("button", name=ui.t("control.confirm_send")).click()
    expect(ui.toast(ui.t("control.ok_toast"))).to_be_visible()
    expect(p.locator("tbody tr").first).to_be_visible()
    row = p.locator("tbody tr").first
    expect(row).to_contain_text(tl)
    p.reload(); p.wait_for_load_state("networkidle")
    chk = p.get_by_role("radiogroup", name=label).get_by_role("radio", name=tl, exact=True)
    expect(chk).to_have_attribute("aria-checked", "true")
    ui.no_h_overflow(); ui.shot("control")


def test_control_unsafe_value_rejected(ui):
    p = ui.page
    ui.login(*DEMO)
    ui.goto("/app/control")
    me = Api(); me.login(*DEMO)
    dev = me.req("GET", "/api/devices").json()[0]["id"]
    # API-level guarantee: unsafe value -> 422 unsafe_value, missing confirm -> 400
    r = me.req("POST", f"/api/devices/{dev}/settings", json={"key": "max_ac_charge_current", "value": 999, "confirm": True})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unsafe_value", r.text
    r = me.req("POST", f"/api/devices/{dev}/settings", json={"key": "buzzer", "value": False})
    assert r.status_code == 400 and r.json()["error"]["code"] == "confirm_required", r.text
    # UI-level: the range check blocks Apply on out-of-range input...
    num = p.get_by_role("spinbutton").first
    num.fill("999")
    expect(p.get_by_role("button", name=ui.t("control.apply"))).to_be_disabled()
    expect(p.get_by_text(ui.t("control.out_of_range"))).to_be_visible()
    # ...and if the request is forced through anyway (tampered), the server error surfaces as an error toast
    num.fill("40")
    def tamper(route):
        body = route.request.post_data_json
        body["value"] = 999
        route.continue_(post_data=__import__("json").dumps(body))
    p.route("**/api/devices/*/settings", lambda route: tamper(route) if route.request.method == "POST" else route.continue_())
    p.get_by_role("button", name=ui.t("control.apply")).click()
    p.get_by_role("dialog").get_by_role("button", name=ui.t("control.confirm_send")).click()
    toast = ui.toast()
    expect(toast).to_be_visible()
    expect(toast).not_to_contain_text(ui.t("control.ok_toast"))
    assert "var(--red)" in (toast.get_attribute("style") or "") or "red" in (toast.get_attribute("style") or "")


def test_free_plan_gating_upsell(ui):
    u = make_user("free", "gate")
    p = ui.page
    a = Api(); a.login(u["email"], u["password"])
    a.req("POST", "/api/sites", json={"name": "S"})
    site = a.req("GET", "/api/sites").json()[0]
    disc = a.req("POST", "/api/integrations/discover", json={"driver": "demo", "credentials": {}}).json()
    d = disc["devices"][0]
    assert a.req("POST", "/api/devices", json={"site_id": site["id"], "driver": "demo", "integration_token": disc["integration_token"], "external_id": d["external_id"], "name": "G"}).status_code in (200, 201)
    ui.login(u["email"], u["password"])
    for path, feat in [("/app/control", "control"), ("/app/automations", "automations")]:
        ui.goto(path)
        expect(p.get_by_text(ui.t("upsell.title")).first).to_be_visible()
        expect(p.get_by_role("link", name=ui.t("upsell.cta")).first).to_be_visible()
    ui.shot("upsell")


# ------------------------------------------------------------------ alerts
def test_alerts_list_markread_and_edit_rule(ui):
    p = ui.page
    ui.login(*DEMO)
    ui.goto("/app/alerts")
    p.get_by_role("tab", name=ui.t("alerts.tab_list")).click()
    expect(p.get_by_text(ui.t("alerts.empty"))).to_have_count(0)
    # mark one read (if any unread remain), then mark all
    btn = p.get_by_role("button", name=ui.t("alerts.mark_read"))
    if btn.count():
        btn.first.click(); p.wait_for_timeout(600)
    mark_all = p.get_by_role("button", name=ui.t("alerts.mark_all"))
    if mark_all.is_enabled():  # unread alerts remain
        mark_all.click()
    p.wait_for_timeout(800)
    expect(p.get_by_role("button", name=ui.t("alerts.mark_all"))).to_be_disabled()
    api = Api(); api.login(*DEMO)
    assert all(a["read"] for a in api.req("GET", "/api/alerts?limit=50").json()["items"])
    ui.shot("alerts")
    # edit rule
    p.get_by_role("tab", name=ui.t("alerts.tab_rules")).click()
    card = p.locator("div.rounded-\\[18px\\]").filter(has=p.get_by_role("heading", name=ui.t("alerts.type_battery_low"), exact=True)).first
    inp = card.get_by_label(ui.t("alerts.p_threshold_soc"))
    new = "37" if inp.input_value() != "37" else "33"
    inp.fill(new)
    card.get_by_role("button", name=ui.t("alerts.save")).click()
    expect(ui.toast(ui.t("alerts.saved"))).to_be_visible()
    rules = api.req("GET", "/api/alert-rules").json()
    rules = rules["items"] if isinstance(rules, dict) else rules
    bl = next(r for r in rules if r["type"] == "battery_low")
    assert str(bl["params"]["threshold_soc"]) == new
    ui.no_h_overflow()


# ------------------------------------------------------------------ automations
def test_automation_create_load_shedding(ui):
    p = ui.page
    ui.login(*DEMO)
    ui.goto("/app/automations")
    p.get_by_role("button", name=ui.t("auto.new")).first.click()
    dlg = p.get_by_role("dialog")
    expect(dlg).to_be_visible()
    name = f"E2E shed {ui.loc}-{ui.vp}-{int(time.time())}"
    dlg.get_by_label(ui.t("auto.name"), exact=True).fill(name)
    # add a condition: battery_soc < 30 (builder starts with sensible defaults; use the template if present)
    ui.shot("automation-builder")
    dlg.get_by_role("button", name=ui.t("auto.save")).click()
    expect(ui.toast(ui.t("auto.saved"))).to_be_visible()
    expect(p.get_by_text(name)).to_be_visible()
    api = Api(); api.login(*DEMO)
    rules = api.req("GET", "/api/automations").json()
    rules = rules["items"] if isinstance(rules, dict) else rules
    assert any(r["name"] == name for r in rules)
    ui.no_h_overflow(); ui.shot("automations")


# ------------------------------------------------------------------ devices
def test_devices_wizard_rename_delete(ui):
    u = make_user("home", "dev")
    p = ui.page
    ui.login(u["email"], u["password"])
    ui.goto("/app/devices")
    p.get_by_role("button", name=ui.t("devices.add")).first.click()
    dlg = p.get_by_role("dialog")
    dlg.get_by_role("button", name=re.compile("Demo|تجريبي|محاكي|demo", re.I)).first.click()
    dlg.get_by_role("button", name=ui.t("devices.discover")).click()
    expect(dlg.get_by_text(ui.t("devices.pick_text"))).to_be_visible()
    dlg.get_by_label(ui.t("devices.name"), exact=True).fill("My Wizard Inverter")
    dlg.get_by_role("button", name=ui.t("devices.next")).click()
    ui.shot("wizard-site")
    dlg.get_by_label(ui.t("devices.site"), exact=True).select_option("__new")
    dlg.get_by_label(ui.t("devices.site_name")).fill("Wizard Site")
    dlg.get_by_role("button", name=ui.t("devices.finish")).click()
    expect(p.get_by_text("My Wizard Inverter").first).to_be_visible()
    # rename
    p.get_by_role("button", name=ui.t("devices.edit"), exact=True).first.click()
    dlg = p.get_by_role("dialog")
    dlg.get_by_label(ui.t("devices.name"), exact=True).fill("Renamed Inverter")
    dlg.get_by_role("button", name=ui.t("devices.save")).click()
    expect(p.get_by_text("Renamed Inverter").first).to_be_visible()
    ui.no_h_overflow(); ui.shot("devices")
    # delete
    p.get_by_role("button", name=ui.t("devices.delete"), exact=True).first.click()
    p.get_by_role("dialog").get_by_role("button", name=ui.t("devices.delete"), exact=True).click()
    expect(p.get_by_text("Renamed Inverter")).to_have_count(0)
    a = Api(); a.login(u["email"], u["password"])
    assert a.req("GET", "/api/devices").json() == []


# ------------------------------------------------------------------ settings
def test_settings_2fa_login_roundtrip(ui):
    u = make_user("pro", "tfa")
    p = ui.page
    ui.login(u["email"], u["password"])
    ui.goto("/app/settings")
    p.get_by_role("tab", name=ui.t("settings.tab_security")).click()
    p.get_by_role("button", name=ui.t("settings.twofa_setup")).click()
    code_el = p.locator("code").first
    expect(code_el).to_be_visible()
    secret = code_el.inner_text().strip()
    expect(p.get_by_alt_text(ui.t("settings.qr_alt"))).to_be_visible()
    p.get_by_label(ui.t("settings.twofa_code")).fill(pyotp.TOTP(secret).now())
    p.get_by_role("button", name=ui.t("settings.twofa_enable")).click()
    expect(ui.toast(ui.t("settings.totp_enabled"))).to_be_visible()
    ui.shot("settings-2fa")
    logout(ui, "E2E User")
    # login without code is refused at the API level and the UI asks for the code
    ui.goto("/login")
    p.get_by_label(ui.t("auth.email")).fill(u["email"])
    p.get_by_label(ui.t("auth.password"), exact=True).fill(u["password"])
    p.locator("button[type=submit]").click()
    expect(p.get_by_label(ui.t("auth.totp_code"))).to_be_visible()
    # wait for the next TOTP window if the same code was just used? (codes can be reused inside a window by default)
    p.get_by_label(ui.t("auth.totp_code")).fill(pyotp.TOTP(secret).now())
    p.locator("button[type=submit]").click()
    p.wait_for_url(re.compile(r"/app/?$"), timeout=20000)
    expect(p.get_by_text(ui.t("empty.title"))).to_be_visible()


def test_settings_api_key_rest_and_mcp(ui):
    u = make_user("pro", "key")
    p = ui.page
    # seed a demo device for the user via API
    a = Api(); a.login(u["email"], u["password"])
    site = a.req("POST", "/api/sites", json={"name": "S"}).json()
    disc = a.req("POST", "/api/integrations/discover", json={"driver": "demo", "credentials": {}}).json()
    d = disc["devices"][0]
    dev = a.req("POST", "/api/devices", json={"site_id": site["id"], "driver": "demo", "integration_token": disc["integration_token"], "external_id": d["external_id"], "name": "K Dev"})
    assert dev.status_code in (200, 201), dev.text
    dev_id = dev.json()["id"]
    ui.login(u["email"], u["password"])
    ui.goto("/app/settings")
    p.get_by_role("tab", name=ui.t("settings.tab_keys")).click()
    p.get_by_label(ui.t("settings.key_name")).fill("e2e key")
    p.get_by_role("button", name=ui.t("settings.create"), exact=True).click()
    dlg = p.get_by_role("dialog")
    key = dlg.locator("code").first.inner_text().strip()
    assert key.startswith("se_live_"), key
    ui.shot("api-key-created")
    dlg.get_by_role("button", name=ui.t("settings.done")).click()
    H = {"Authorization": f"Bearer {key}"}
    r = requests.get(f"{WEB}/api/devices", headers=H)
    assert r.status_code == 200 and any(x["id"] == dev_id for x in r.json()), r.text
    # MCP streamable HTTP (via the frontend proxy, same as a client would use)
    mh = {**H, "Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    def rpc(method, params=None, id_=1, sid=None):
        h = dict(mh)
        if sid: h["mcp-session-id"] = sid
        body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if id_ is not None: body["id"] = id_
        r = requests.post(f"{WEB}/mcp", headers=h, json=body, timeout=30)
        return r
    r = rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "e2e", "version": "1"}})
    assert r.status_code == 200, r.text
    sid = r.headers.get("mcp-session-id")
    def parse(r):
        t = r.text
        if "data:" in t:
            t = [l[5:].strip() for l in t.splitlines() if l.startswith("data:")][-1]
        return __import__("json").loads(t)
    assert parse(r)["result"]["serverInfo"]
    rpc("notifications/initialized", id_=None, sid=sid)
    tools = parse(rpc("tools/list", id_=2, sid=sid))["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"list_devices", "get_live_status", "get_today_summary", "get_history", "list_alerts", "get_settings", "change_setting"} <= names, names
    res = parse(rpc("tools/call", {"name": "get_live_status", "arguments": {"device_id": dev_id}}, id_=3, sid=sid))
    assert "result" in res and not res["result"].get("isError"), res
    assert "metrics" in __import__("json").dumps(res["result"]) or "online" in __import__("json").dumps(res["result"])
    # revoke in the UI
    p.get_by_role("button", name=ui.t("settings.revoke")).first.click()
    p.get_by_role("dialog").get_by_role("button", name=ui.t("settings.revoke")).click()
    p.wait_for_timeout(800)
    assert requests.get(f"{WEB}/api/devices", headers=H).status_code == 401


def test_settings_telegram_link(ui):
    u = make_user("pro", "tg")
    p = ui.page
    ui.login(u["email"], u["password"])
    ui.goto("/app/settings")
    p.get_by_role("tab", name=ui.t("settings.tab_notifications")).click()
    p.get_by_role("button", name=ui.t("settings.tg_link")).click()
    expect(p.get_by_text(ui.t("settings.tg_manual"))).to_be_visible()
    expect(p.get_by_role("link", name=re.compile("@"))).to_have_attribute("href", re.compile(r"^https://t\.me/.+\?start=[A-Za-z0-9_-]+$"))
    ui.shot("settings-telegram")
    ui.no_h_overflow()


def test_settings_profile_and_plan_tabs_render(ui):
    ui.login(*DEMO)
    ui.goto("/app/settings")
    for k in ["tab_profile", "tab_security", "tab_notifications", "tab_keys", "tab_team", "tab_plan"]:
        ui.page.get_by_role("tab", name=ui.t(f"settings.{k}")).click()
        ui.page.wait_for_timeout(300)
        ui.no_h_overflow(); ui.assert_no_raw_keys()


# ------------------------------------------------------------------ assistant
def test_assistant_unavailable_message(ui):
    p = ui.page
    ui.login(*DEMO)
    ui.goto("/app/assistant")
    box = p.get_by_placeholder(ui.t("assistant.placeholder"))
    box.fill("How is my system?")
    p.get_by_role("button", name=ui.t("assistant.send")).click()
    expect(p.get_by_text(ui.t("assistant.unavailable_msg")).first).to_be_visible()
    ui.no_h_overflow(); ui.shot("assistant")


# ------------------------------------------------------------------ admin
def test_admin_stats_and_change_tenant_plan(ui):
    u = make_user("free", "adm", tenant=f"Plan Change {uniq_email('t')[:12]}")
    api = admin_api()
    p = ui.page
    ui.login(*ADMIN, expect="/app")
    ui.goto("/admin")
    expect(p.get_by_text(ui.t("admin.title")).first).to_be_visible()
    for k in ["admin.tenants", "admin.users", "admin.devices", "admin.mrr"]:
        expect(p.locator("main").get_by_text(ui.t(k)).locator("visible=true").first).to_be_visible()
    ui.shot("admin")
    p.get_by_role("tab", name=ui.t("admin.tab_tenants")).click()
    p.get_by_role("searchbox", name=ui.t("admin.search")).fill(u["tenant_id"][:0] or "Plan Change")
    p.wait_for_timeout(1200)
    me = Api(); me.login(u["email"], u["password"])
    tname = me.req("GET", "/api/tenant").json()["name"]
    p.get_by_role("searchbox", name=ui.t("admin.search")).fill(tname)
    p.wait_for_timeout(1200)
    row = p.locator("tr").filter(has_text=tname).first
    row.get_by_role("button", name=ui.t("admin.edit")).click()
    dlg = p.get_by_role("dialog")
    dlg.get_by_label(ui.t("admin.col_plan"), exact=True).select_option("installer")
    dlg.get_by_role("button", name=ui.t("admin.save")).click()
    expect(ui.toast(ui.t("admin.saved"))).to_be_visible()
    assert me.req("GET", "/api/tenant").json()["plan"]["code"] == "installer"
    ui.no_h_overflow()


# ------------------------------------------------------------------ installer
def test_installer_branding_customers_switch(ui):
    u = make_user("installer", "inst", tenant="Inst Co")
    p = ui.page
    ui.login(u["email"], u["password"])
    ui.goto("/app/branding")
    expect(p.get_by_text(ui.t("brand.title")).first).to_be_visible()
    before = p.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent')")
    p.get_by_label(ui.t("brand.name_en")).fill("Sunrise Solar")
    p.get_by_label(ui.t("brand.name_ar")).fill("شمس الصباح")
    p.get_by_label(ui.t("brand.primary")).last.fill("#2563EB")
    p.get_by_label(ui.t("brand.accent")).last.fill("#16A34A")
    p.get_by_role("button", name=ui.t("brand.save")).click()
    expect(ui.toast(ui.t("brand.saved"))).to_be_visible()
    p.wait_for_timeout(800)
    after = p.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent')")
    assert before.strip().lower() != after.strip().lower(), f"accent unchanged {before} -> {after}"
    api = Api(); api.login(u["email"], u["password"])
    br = api.req("GET", "/api/tenant").json()["branding"]
    assert br["name"] == "Sunrise Solar" and br["primary_color"].lower() == "#2563eb"
    ui.shot("branding")
    # customers
    ui.goto("/app/customers")
    expect(p.get_by_text(ui.t("customers.empty")).first).to_be_visible()
    p.get_by_role("button", name=ui.t("customers.add")).first.click()
    dlg = p.get_by_role("dialog")
    dlg.get_by_label(ui.t("customers.f_name")).fill("Customer One")
    dlg.get_by_label(ui.t("customers.f_owner_name")).fill("Cust Owner")
    dlg.get_by_label(ui.t("customers.f_owner_email")).fill(uniq_email("cust"))
    dlg.get_by_label(ui.t("customers.f_password")).fill(PW)
    dlg.get_by_role("button", name=ui.t("customers.create")).click()
    expect(ui.toast(ui.t("customers.created"))).to_be_visible()
    expect(p.get_by_text("Customer One").locator("visible=true").first).to_be_visible()
    ui.shot("customers")
    p.get_by_role("button", name=ui.t("customers.open")).locator("visible=true").first.click()
    p.wait_for_url(re.compile(r"/app/?$"))
    p.wait_for_load_state("networkidle")
    assert api.req("GET", "/api/customers").json()["items"][0]["name"] == "Customer One"
    # switch back through the account switcher
    sw = p.get_by_label(ui.t("shell.switch_tenant"))
    expect(sw).to_be_visible()
    expect(sw).to_contain_text("Customer One")
    sw.click()
    p.get_by_role("option").filter(has_text="Inst Co").click()
    expect(p.get_by_label(ui.t("shell.switch_tenant"))).to_contain_text("Inst Co")
    ui.no_h_overflow()
