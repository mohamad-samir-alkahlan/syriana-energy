"""API-level / security / white-label tests (run once, no browser locale matrix)."""
from __future__ import annotations

import re

import requests

from conftest import WEB, Api, admin_api, make_user, uniq_email, PW


def _dev_for(u):
    a = Api(); a.login(u["email"], u["password"])
    site = a.req("POST", "/api/sites", json={"name": "S"}).json()
    disc = a.req("POST", "/api/integrations/discover", json={"driver": "demo", "credentials": {}}).json()
    d = disc["devices"][0]
    r = a.req("POST", "/api/devices", json={"site_id": site["id"], "driver": "demo", "integration_token": disc["integration_token"], "external_id": d["external_id"], "name": "D"})
    assert r.status_code in (200, 201), r.text
    return a, r.json()["id"]


def test_cross_tenant_isolation_and_unauth():
    ua, ub = make_user("home", "a"), make_user("home", "b")
    a, dev_a = _dev_for(ua)
    b = Api(); b.login(ub["email"], ub["password"])
    for path in [f"/api/devices/{dev_a}", f"/api/devices/{dev_a}/live", f"/api/devices/{dev_a}/today", f"/api/devices/{dev_a}/history", f"/api/devices/{dev_a}/energy"]:
        r = b.req("GET", path)
        assert r.status_code == 404, (path, r.status_code, r.text)
    assert b.req("DELETE", f"/api/devices/{dev_a}").status_code == 404
    assert b.req("PATCH", f"/api/devices/{dev_a}", json={"name": "x"}).status_code == 404
    assert dev_a not in [d["id"] for d in b.req("GET", "/api/devices").json()]
    # owner still fine
    assert a.req("GET", f"/api/devices/{dev_a}").status_code == 200
    # no cookie -> 401
    for path in ["/api/auth/me", "/api/devices", "/api/sites", "/api/alerts", "/api/tenant", f"/api/devices/{dev_a}/live"]:
        r = requests.get(WEB + path)
        assert r.status_code == 401, (path, r.status_code)
        assert "error" in r.json()
    assert requests.get(WEB + "/api/admin/stats").status_code == 401
    # normal user is not an admin
    assert a.req("GET", "/api/admin/stats").status_code in (401, 403)
    # bad API key
    assert requests.get(WEB + "/api/devices", headers={"Authorization": "Bearer se_live_nope"}).status_code == 401


def test_session_cookie_flags():
    r = requests.post(WEB + "/api/auth/login", json={"email": "demo@syriana.energy", "password": "demo12345"})
    sc = r.headers["set-cookie"]
    assert "se_session=" in sc and "httponly" in sc.lower() and "samesite=lax" in sc.lower()


def test_browser_cannot_read_session_cookie(browser):
    from conftest import DEMO
    c = browser.new_context(); p = c.new_page()
    p.goto(WEB + "/en/login"); p.get_by_label("Email").fill(DEMO[0]); p.get_by_label("Password", exact=True).fill(DEMO[1])
    p.locator("button[type=submit]").click(); p.wait_for_url(re.compile(r"/app"))
    assert "se_session" not in p.evaluate("document.cookie")
    ck = [x for x in c.cookies() if x["name"] == "se_session"]
    assert ck and ck[0]["httpOnly"]
    c.close()


def test_white_label_host_branding():
    u = make_user("installer", "wl", tenant="WL Co")
    a = Api(); a.login(u["email"], u["password"])
    dom = f"energy{uniq_email('d')[2:10]}.example.com"
    name = "Noor Solar WL"
    r = a.req("PATCH", "/api/tenant/branding", json={"name": name, "name_ar": "نور سولار", "logo_url": None, "primary_color": "#2563EB", "accent_color": "#16A34A", "support_email": "s@example.com", "custom_domain": dom})
    assert r.status_code == 200, r.text
    # branding endpoint through the proxy
    b = requests.get(WEB + "/api/public/branding", params={"host": dom}).json()
    assert b["name"] == name and b["primary_color"].lower() == "#2563eb"
    # frontend requested with the custom Host header (SSR picks up branding)
    for loc, expect_name in [("en", name), ("ar", "نور سولار")]:
        html = requests.get(f"{WEB}/{loc}", headers={"Host": dom}).text
        assert expect_name in html, f"{loc}: branding name missing from HTML for host {dom}"
        assert "#2563eb" in html.lower() or "#2563EB" in html, "primary colour not injected"
    # unknown host falls back to platform default
    html = requests.get(f"{WEB}/en", headers={"Host": "unknown.example.org"}).text
    assert "Syriana Energy" in html and name not in html


def test_api_contract_basics():
    h = requests.get(WEB + "/api/health").json(); assert h["ok"] is True
    p = requests.get(WEB + "/api/public/plans").json()
    assert {x["code"] for x in p} >= {"free", "home", "pro", "installer"}
    d = requests.get(WEB + "/api/public/branding").json()
    assert d["name"] == "Syriana Energy" and d["primary_color"].lower() == "#da7756"
    r = requests.post(WEB + "/api/auth/login", json={"email": "demo@syriana.energy", "password": "bad"})
    assert r.status_code == 401 and set(r.json()["error"]) >= {"code", "message", "message_ar"}
    # validation errors keep the contract's shape
    r = requests.post(WEB + "/api/auth/register", json={"email": "not-an-email", "password": "x"})
    assert r.status_code in (400, 422) and "error" in r.json(), r.text


def test_plan_limits_enforced():
    u = make_user("free", "lim")
    a = Api(); a.login(u["email"], u["password"])
    site = a.req("POST", "/api/sites", json={"name": "S"}).json()
    codes = []
    for i in range(4):
        disc = a.req("POST", "/api/integrations/discover", json={"driver": "demo", "credentials": {}}).json()
        d = disc["devices"][0]
        r = a.req("POST", "/api/devices", json={"site_id": site["id"], "driver": "demo", "integration_token": disc["integration_token"], "external_id": d["external_id"] + str(i), "name": f"D{i}"})
        codes.append(r.status_code)
    assert 403 in codes, codes
