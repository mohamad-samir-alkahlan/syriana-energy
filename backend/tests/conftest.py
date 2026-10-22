from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", "postgresql://se:se@localhost:5432/syriana_energy_test"),
    "REDIS_URL": "",
    "JWT_SECRET": "test-secret-test-secret-test-secret-123456",
    "ODOO_WEBHOOK_SECRET": "odoo-test-secret",
    "TELEGRAM_BOT_TOKEN": "",
    "TELEGRAM_WEBHOOK_SECRET": "whsec-test",
    "TELEGRAM_BOT_USERNAME": "TestBot",
    "ANTHROPIC_API_KEY": "",
    "SMTP_HOST": "",
    "ALLOW_PRIVATE_URLS": "false",
})
from cryptography.fernet import Fernet  # noqa: E402

os.environ["CREDENTIALS_KEY"] = Fernet.generate_key().decode()

import asyncpg  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import text, update  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


def _raw_dsn() -> str:
    return os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    """Fresh schema built by the real Alembic migrations."""
    async def reset():
        conn = await asyncpg.connect(_raw_dsn())
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        await conn.close()
    asyncio.run(reset())
    env = {**os.environ, "DATABASE_URL": _raw_dsn()}
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    yield


from app import clock  # noqa: E402
from app.cache import limiter  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Tenant, User  # noqa: E402
from app.services import notify  # noqa: E402

TABLES = ("alert_state, alerts, alert_rules, automations, commands, audit_log, readings, devices, sites, api_keys, "
          "telegram_link_codes, billing_events, kv, sessions, memberships, users, tenants")


class FakeTransports:
    """Records outbound notifications instead of calling the network."""

    def __init__(self):
        self.telegram_msgs: list[tuple] = []
        self.emails: list[tuple] = []
        self.webhooks: list[tuple] = []
        self.http_calls: list[tuple] = []
        self.fail_http = False

    async def telegram(self, chat_id, text, html_mode=True):
        self.telegram_msgs.append((chat_id, text))
        return True

    async def email(self, to, subject, body):
        self.emails.append((to, subject, body))
        return True

    async def webhook(self, url, payload):
        self.webhooks.append((url, payload))
        return True

    async def http_action(self, method, url, body):
        if self.fail_http:
            raise ValueError("HTTP 500")
        self.http_calls.append((method, url, body))
        return True


@pytest_asyncio.fixture(autouse=True)
async def clean(monkeypatch):
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} CASCADE"))
    from app.plans import seed_plans
    async with SessionLocal() as sess:  # tests may edit plans; always start from the catalog defaults
        await seed_plans(sess, overwrite=True)
        await sess.commit()
    limiter.clear()
    clock.set_now(None)
    from app.drivers import eybond_cloud
    eybond_cloud._SESSIONS.clear()
    fake = FakeTransports()
    monkeypatch.setattr(notify, "transports", fake)
    yield fake
    clock.set_now(None)


@pytest.fixture
def fake(clean) -> FakeTransports:
    return clean


@pytest_asyncio.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def db():
    async with SessionLocal() as s:
        yield s


_n = 0


async def register(c: httpx.AsyncClient, email: str | None = None, password: str = "password123", name: str = "Test",
                   tenant_name: str = "Home", locale: str = "ar") -> dict:
    global _n
    _n += 1
    email = email or f"user{_n}-{uuid.uuid4().hex[:6]}@example.com"
    r = await c.post("/api/auth/register", json={"email": email, "password": password, "name": name,
                                                 "tenant_name": tenant_name, "locale": locale})
    assert r.status_code == 201, r.text
    return r.json()


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def set_plan(tenant_id: str, code: str, expires: datetime | None = None, type_: str | None = None) -> None:
    async with SessionLocal() as s:
        t = await s.get(Tenant, uuid.UUID(tenant_id))
        t.plan_code, t.plan_expires_at = code, expires
        if type_:
            t.type = type_
        await s.commit()


async def make_superadmin(email: str) -> None:
    async with SessionLocal() as s:
        await s.execute(update(User).where(User.email == email).values(is_superadmin=True))
        await s.commit()


async def add_demo_device(c: httpx.AsyncClient, name: str = "Demo") -> dict:
    sites = (await c.get("/api/sites")).json()
    r = await c.post("/api/devices", json={"site_id": sites[0]["id"], "driver": "demo", "credentials": {},
                                            "external_id": f"demo-{uuid.uuid4().hex[:8]}", "name": name})
    assert r.status_code == 201, r.text
    return r.json()


@pytest_asyncio.fixture
async def home(client):
    """A signed-in home tenant on the `pro` plan with one demo device."""
    me = await register(client)
    await set_plan(me["tenant"]["id"], "pro")
    dev = await add_demo_device(client)
    return {"me": me, "device": dev, "client": client}


UTC = timezone.utc


def dt(y, mo, d, h=0, mi=0, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=UTC)
