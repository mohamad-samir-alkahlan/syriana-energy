"""Shared fixtures/helpers for the Syriana Energy full-stack E2E suite."""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

import pytest
import requests
from playwright.sync_api import sync_playwright

WEB = os.environ.get("E2E_WEB", "http://localhost:3000")
ROOT = Path(__file__).resolve().parent
MESSAGES = ROOT.parent / "frontend" / "messages"
SCREENS = ROOT / "screens"
ADMIN = ("admin@syriana.energy", "Admin12345!")
DEMO = ("demo@syriana.energy", "demo12345")
PW = "E2ePass12345"

LOCALES = ["ar", "en"]
VIEWPORTS = {"desktop": (1280, 800), "mobile": (390, 844)}


def pytest_generate_tests(metafunc):
    if "loc" in metafunc.fixturenames and "vp" in metafunc.fixturenames:
        ids, params = [], []
        for l in LOCALES:
            for v in VIEWPORTS:
                params.append((l, v))
                ids.append(f"{l}-{v}")
        metafunc.parametrize("loc,vp", params, ids=ids)


_msgs: dict[str, dict] = {}


def tr(loc: str, key: str, **kw) -> str:
    """Look a UI string up in frontend/messages/<loc>.json ('ns.key'); simple {x} substitution."""
    if loc not in _msgs:
        _msgs[loc] = json.loads((MESSAGES / f"{loc}.json").read_text(encoding="utf-8"))
    cur = _msgs[loc]
    for part in key.split("."):
        cur = cur[part]
    for k, v in kw.items():
        cur = cur.replace("{" + k + "}", str(v))
    return cur


def uniq_email(prefix="u") -> str:
    return f"{prefix}.{uuid.uuid4().hex[:10]}@e2email.com"


# ---------------- API helpers (through the frontend proxy, like a browser) ----------------
class Api:
    def __init__(self, base=WEB):
        self.base = base
        self.s = requests.Session()

    def req(self, method, path, **kw):
        return self.s.request(method, self.base + path, timeout=30, **kw)

    def login(self, email, password, totp=None):
        body = {"email": email, "password": password}
        if totp:
            body["totp_code"] = totp
        r = self.req("POST", "/api/auth/login", json=body)
        assert r.status_code == 200, r.text
        return r.json()

    def register(self, email, name="E2E User", tenant="E2E Home", locale="en"):
        r = self.req("POST", "/api/auth/register", json={"email": email, "password": PW, "name": name, "tenant_name": tenant, "locale": locale})
        assert r.status_code == 201, r.text
        return r.json()


def admin_api() -> Api:
    a = Api()
    a.login(*ADMIN)
    return a


def make_user(plan="free", prefix="u", tenant="E2E Home") -> dict:
    """Register a fresh user via the API; optionally set the tenant plan through the superadmin API."""
    email = uniq_email(prefix)
    a = Api()
    me = a.register(email, tenant=tenant)
    if plan != "free":
        ad = admin_api()
        r = ad.req("PATCH", f"/api/admin/tenants/{me['tenant']['id']}", json={"plan_code": plan})
        assert r.status_code == 200, r.text
    return {"email": email, "password": PW, "tenant_id": me["tenant"]["id"]}


# ---------------- browser fixtures ----------------
@pytest.fixture(scope="session")
def pw():
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def browser(pw):
    b = pw.chromium.launch()
    yield b
    b.close()


@pytest.fixture
def ctx(browser, loc, vp):
    w, h = VIEWPORTS[vp]
    c = browser.new_context(viewport={"width": w, "height": h}, locale="ar-SY" if loc == "ar" else "en-US", accept_downloads=True)
    c.set_default_timeout(15000)
    yield c
    c.close()


IGNORED_CONSOLE = re.compile(r"Failed to load resource|status of 4\d\d|the server responded with a status of")


@pytest.fixture
def page(ctx, request):
    pg = ctx.new_page()
    pg.problems = []  # type: ignore[attr-defined]
    pg.on("pageerror", lambda e: pg.problems.append(f"pageerror: {e}"))
    pg.on("console", lambda m: pg.problems.append(f"console.{m.type}: {m.text}") if m.type == "error" and not IGNORED_CONSOLE.search(m.text) else None)
    pg.on("response", lambda r: pg.problems.append(f"HTTP {r.status} {r.url}") if r.status >= 500 and not (r.status == 503 and "/assistant/chat" in r.url) else None)
    yield pg
    assert not pg.problems, "runtime problems:\n" + "\n".join(pg.problems[:10])


class Ui:
    """Locale/viewport-aware helpers around a Playwright page."""

    def __init__(self, page, loc, vp):
        self.page, self.loc, self.vp = page, loc, vp

    def t(self, key, **kw):
        return tr(self.loc, key, **kw)

    def url(self, path=""):
        return f"{WEB}/{self.loc}{path}"

    def goto(self, path=""):
        self.page.goto(self.url(path))
        self.page.wait_for_load_state("networkidle")

    def login(self, email, password, totp=None, expect="/app"):
        p = self.page
        self.goto("/login")
        p.get_by_label(self.t("auth.email")).fill(email)
        p.get_by_label(self.t("auth.password"), exact=True).fill(password)
        p.locator("button[type=submit]").click()
        if totp:
            p.get_by_label(self.t("auth.totp_code")).fill(totp)
            p.locator("button[type=submit]").click()
        p.wait_for_url(re.compile(re.escape(expect)), timeout=20000)

    def toast(self, text=None):
        loc = self.page.locator("[role=status] > div")
        if text:
            loc = loc.filter(has_text=text)
        return loc.first

    def no_h_overflow(self):
        over = self.page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        assert over <= 1, f"horizontal overflow {over}px at {self.page.url}"

    def assert_no_raw_keys(self):
        txt = self.page.inner_text("body")
        bad = re.findall(r"\b(?:common|nav|shell|dash|auth|devices|settings|control|alerts|auto|brand|admin|landing|empty|history|customers|assistant|flow|upsell)\.[a-z_0-9]{2,}\b", txt)
        assert not bad, f"untranslated keys visible: {bad[:5]}"

    def shot(self, name):
        SCREENS.mkdir(exist_ok=True)
        self.page.screenshot(path=str(SCREENS / f"{self.loc}-{self.vp}-{name}.png"), full_page=True)


@pytest.fixture
def ui(page, loc, vp):
    return Ui(page, loc, vp)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    out = yield
    rep = out.get_result()
    if rep.when == "call" and rep.failed and "page" in item.funcargs:
        try:
            d = SCREENS / "failures"
            d.mkdir(parents=True, exist_ok=True)
            item.funcargs["page"].screenshot(path=str(d / f"{item.name}.png"), full_page=True)
        except Exception:
            pass
