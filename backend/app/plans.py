"""Plan catalog + seeding. Features are enforced server-side."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Plan

ALL_FEATURES = ["control", "ai", "email", "webhook", "automations", "api", "white_label", "customers"]
HOME_FEATURES = ["control", "ai", "email", "webhook", "automations", "api"]

PLAN_DEFS: list[dict[str, Any]] = [
    dict(code="free", name="Free", name_ar="مجاني", price_month=0.0, price_year=0.0, max_devices=1,
         history_days=7, features=[], per_device=False, sort=0),
    dict(code="home", name="Home", name_ar="بيت", price_month=4.0, price_year=40.0, max_devices=3,
         history_days=365, features=HOME_FEATURES, per_device=False, sort=1),
    dict(code="pro", name="Pro", name_ar="احترافي", price_month=9.0, price_year=90.0, max_devices=10,
         history_days=730, features=HOME_FEATURES, per_device=False, sort=2),
    # installer: price is PER DEVICE per month
    dict(code="installer", name="Installer", name_ar="مُركِّب", price_month=2.0, price_year=20.0, max_devices=500,
         history_days=730, features=ALL_FEATURES, per_device=True, sort=3),
]


async def seed_plans(db: AsyncSession, overwrite: bool = False) -> int:
    n = 0
    for d in PLAN_DEFS:
        row = (await db.execute(select(Plan).where(Plan.code == d["code"]))).scalar_one_or_none()
        if row is None:
            db.add(Plan(currency="USD", **d))
            n += 1
        elif overwrite:
            for k, v in d.items():
                setattr(row, k, v)
            n += 1
    await db.flush()
    return n
