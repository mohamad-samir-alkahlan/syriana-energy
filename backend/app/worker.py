"""Background worker: device polling, alert/automation evaluation, maintenance, Telegram long-polling.

Run: python -m app.worker
"""
from __future__ import annotations

import asyncio
import logging
import signal
import time
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update

from app import clock
from app.cache import get_redis
from app.config import settings
from app.db import SessionLocal, engine
from app.models import Alert, Device, Reading, Tenant
from app.services import alerts as alert_svc
from app.services import devices as dv
from app.services import polling, telegram
from app.services.tenants import effective_plan

log = logging.getLogger("worker")
MAX_BACKOFF = 300
CONCURRENCY = 10


async def expire_plans(db, now: datetime) -> int:
    """Downgrade tenants whose paid plan has expired to `free` (and tell them in-app)."""
    rows = (await db.execute(select(Tenant).where(Tenant.plan_code != "free", Tenant.plan_expires_at.is_not(None),
                                                  Tenant.plan_expires_at < now))).scalars().all()
    for t in rows:
        old = t.plan_code
        t.plan_code, t.plan_expires_at = "free", None
        await db.refresh(t, attribute_names=["plan"])
        db.add(Alert(tenant_id=t.id, type="plan_expired", severity="warning", title="Plan expired",
                     title_ar="انتهى اشتراكك", body=f"Your {old} plan expired; the account is now on the Free plan.",
                     body_ar=f"انتهت باقة {old} وتم تحويل الحساب إلى الباقة المجانية.", created_at=now))
        log.info("tenant %s plan %s expired -> free", t.id, old)
    await db.flush()
    return len(rows)


async def purge_readings(db, now: datetime) -> int:
    """Retention: drop readings older than the tenant's plan history window."""
    total = 0
    tenants = (await db.execute(select(Tenant))).scalars().all()
    for t in tenants:
        days = (await effective_plan(db, t)).history_days
        ids = select(Device.id).where(Device.tenant_id == t.id)
        res = await db.execute(delete(Reading).where(Reading.device_id.in_(ids), Reading.ts < now - timedelta(days=days)))
        total += res.rowcount or 0
    return total


async def maintenance_tick(now: datetime | None = None) -> dict[str, int]:
    now = now or clock.utcnow()
    out = {}
    async with SessionLocal() as db:
        await polling.refresh_online_flags(db, now)
        out["expired"] = await expire_plans(db, now)
        out["offline"] = len(await alert_svc.check_offline(db, now))
        out["summaries"] = len(await alert_svc.check_daily_summary(db, now))
        await db.commit()
    return out


async def _sleep(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), seconds)
    except asyncio.TimeoutError:
        pass


async def poll_scheduler(stop: asyncio.Event) -> None:
    next_due: dict[uuid.UUID, float] = {}
    fails: dict[uuid.UUID, int] = {}
    running: set[uuid.UUID] = set()
    sem = asyncio.Semaphore(CONCURRENCY)

    async def run_one(did: uuid.UUID, driver: str) -> None:
        interval = dv.poll_interval(driver)
        try:
            async with sem:
                r = await get_redis()
                if r is not None:
                    try:  # one worker per device per interval, even with several worker replicas
                        if not await r.set(f"poll:{did}", "1", nx=True, ex=max(1, interval - 1)):
                            return
                    except Exception:  # noqa: BLE001
                        pass
                async with SessionLocal() as db:
                    try:
                        res = await polling.poll_device(db, did)
                        await db.commit()
                    except Exception:  # noqa: BLE001
                        await db.rollback()
                        log.exception("poll crashed for %s", did)
                        res = None
            if res is None:
                fails[did] = fails.get(did, 0) + 1
                interval = min(interval * (2 ** min(fails[did], 5)), MAX_BACKOFF)
            else:
                fails[did] = 0
                for a in res["alerts"]:
                    log.info("alert %s for %s", a["type"], a.get("device_name"))
        finally:
            next_due[did] = time.monotonic() + interval
            running.discard(did)

    while not stop.is_set():
        try:
            async with SessionLocal() as db:
                devices = await polling.due_devices(db)
            now = time.monotonic()
            alive = {d for d, _ in devices}
            for gone in set(next_due) - alive:
                next_due.pop(gone, None)
                fails.pop(gone, None)
            for did, drv in devices:
                if did not in running and next_due.get(did, 0) <= now:
                    running.add(did)
                    asyncio.create_task(run_one(did, drv))
        except Exception:  # noqa: BLE001
            log.exception("scheduler loop error")
        await _sleep(stop, 1.0)


async def maintenance_loop(stop: asyncio.Event) -> None:
    last_purge = 0.0
    while not stop.is_set():
        try:
            r = await maintenance_tick()
            if any(r.values()):
                log.info("maintenance: %s", r)
            if time.monotonic() - last_purge > 3600:
                async with SessionLocal() as db:
                    n = await purge_readings(db, clock.utcnow())
                    await db.commit()
                last_purge = time.monotonic()
                if n:
                    log.info("retention purge removed %d readings", n)
        except Exception:  # noqa: BLE001
            log.exception("maintenance error")
        await _sleep(stop, 30.0)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings.validate_production()
    from app.startup import ensure_hypertable
    log.info("storage mode: %s", await ensure_hypertable())
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    tasks = [asyncio.create_task(poll_scheduler(stop)), asyncio.create_task(maintenance_loop(stop))]
    if settings.telegram_bot_token:
        tasks.append(asyncio.create_task(telegram.poll_forever(SessionLocal, stop)))
    else:
        log.info("TELEGRAM_BOT_TOKEN not set: telegram polling disabled")
    log.info("worker started")
    await stop.wait()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
