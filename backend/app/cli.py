"""CLI: python -m app.cli {create-superadmin,seed-plans,seed-demo}"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import clock
from app.config import settings
from app.db import SessionLocal, engine
from app.drivers.base import DeviceContext
from app.drivers.registry import get_driver
from app.models import Device, Membership, Site, Tenant, User
from app.plans import seed_plans
from app.security import encrypt_json, hash_password
from app.services import readings as rd
from app.services.tenants import create_tenant

DEMO_EMAIL, DEMO_PASSWORD = "demo@syriana.energy", "demo12345"


async def create_superadmin(email: str, password: str, name: str = "Platform Admin") -> str:
    email = email.lower()
    async with SessionLocal() as db:
        await seed_plans(db)
        u = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if u is None:
            u = User(email=email, name=name, password_hash=hash_password(password), locale="en", is_superadmin=True,
                     email_verified_at=clock.utcnow())
            db.add(u)
            await db.flush()
            t = await create_tenant(db, "Syriana Platform", "home", None, "pro", "en")
            db.add(Membership(user_id=u.id, tenant_id=t.id, role="owner"))
            msg = f"created superadmin {email}"
        else:
            u.is_superadmin = True
            u.password_hash = hash_password(password)
            msg = f"promoted {email} to superadmin and reset the password"
        await db.commit()
    return msg


async def seed_demo(speed: float = 1.0, backfill_hours: int = 24) -> str:
    async with SessionLocal() as db:
        await seed_plans(db)
        u = (await db.execute(select(User).where(User.email == DEMO_EMAIL))).scalar_one_or_none()
        if u is None:
            u = User(email=DEMO_EMAIL, name="Demo User", password_hash=hash_password(DEMO_PASSWORD), locale="ar",
                     email_verified_at=clock.utcnow())
            db.add(u)
            await db.flush()
            t = await create_tenant(db, "Demo Home", "home", None, "pro", "ar")
            db.add(Membership(user_id=u.id, tenant_id=t.id, role="owner"))
            await db.flush()
        else:
            t = (await db.execute(select(Tenant).join(Membership, Membership.tenant_id == Tenant.id)
                                  .where(Membership.user_id == u.id).order_by(Tenant.created_at).limit(1))).scalar_one()
        if t.plan_code == "free":
            t.plan_code = "pro"
            await db.refresh(t, attribute_names=["plan"])
        dev = (await db.execute(select(Device).where(Device.tenant_id == t.id, Device.driver == "demo"))).scalars().first()
        if dev is None:
            site = (await db.execute(select(Site).where(Site.tenant_id == t.id).limit(1))).scalar_one()
            driver = get_driver("demo")
            creds = {"speed": speed} if speed != 1.0 else {}
            model, serial = driver.identify("demo-24v-1")
            dev = Device(tenant_id=t.id, site_id=site.id, name="Demo Inverter 24V", kind="inverter", driver="demo",
                         model=model, serial=serial, external_id="demo-24v-1",
                         credentials_enc=encrypt_json(creds) if creds else None, state={})
            db.add(dev)
            await db.flush()
            if backfill_hours > 0:
                await _backfill(db, dev, backfill_hours)
        await db.commit()
        return f"demo ready: {DEMO_EMAIL} / {DEMO_PASSWORD}  tenant={t.id} device={dev.id}"


async def _backfill(db, dev: Device, hours: int) -> None:
    """Simulate the past `hours` at 1-minute resolution so charts are not empty."""
    from app.services.devices import load_ctx
    driver = get_driver("demo")
    ctx: DeviceContext = await load_ctx(db, dev)
    ctx.credentials = {}  # history is simulated in real time; `speed` only applies to live polling
    end = datetime.now(timezone.utc)
    t = end - timedelta(hours=hours)
    rows = []
    try:
        while t < end:
            clock.set_now(t)
            m, raw = await driver.read(ctx)
            rows.append((t, m, raw))
            t += timedelta(minutes=1)
    finally:
        clock.set_now(None)
    for ts, m, raw in rows:
        await rd.store_reading(db, dev.id, ts, m, raw)
    dev.state = dict(ctx.state)
    dev.last_seen, dev.last_metrics, dev.last_raw = rows[-1][0], rows[-1][1], rows[-1][2]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("create-superadmin")
    a.add_argument("--email", default=settings.superadmin_email or None, required=not settings.superadmin_email)
    a.add_argument("--password", required=True)
    a.add_argument("--name", default="Platform Admin")
    sp = sub.add_parser("seed-plans")
    sp.add_argument("--reset", action="store_true", help="overwrite existing plans with the defaults")
    d = sub.add_parser("seed-demo")
    d.add_argument("--speed", type=float, default=1.0, help="simulated-time multiplier for the demo device")
    d.add_argument("--backfill-hours", type=int, default=24)
    args = ap.parse_args(argv)

    async def run() -> str:
        try:
            if args.cmd == "create-superadmin":
                return await create_superadmin(args.email, args.password, args.name)
            if args.cmd == "seed-plans":
                async with SessionLocal() as db:
                    n = await seed_plans(db, overwrite=args.reset)
                    await db.commit()
                return f"plans seeded/updated: {n}"
            return await seed_demo(args.speed, args.backfill_hours)
        finally:
            await engine.dispose()

    print(asyncio.run(run()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
