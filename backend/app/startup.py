"""Idempotent runtime checks (TimescaleDB hypertable detection)."""
from __future__ import annotations

import logging

from sqlalchemy import text

from app.db import engine

log = logging.getLogger(__name__)


async def ensure_hypertable() -> str:
    """Make `readings` a hypertable if timescaledb is installed; returns 'hypertable' | 'plain'."""
    try:
        async with engine.begin() as conn:
            avail = (await conn.execute(text("SELECT 1 FROM pg_available_extensions WHERE name='timescaledb'"))).scalar()
            if not avail:
                return "plain"
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
            is_ht = (await conn.execute(text(
                "SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name='readings'"))).scalar()
            if not is_ht:
                await conn.execute(text("SELECT create_hypertable('readings','ts', if_not_exists => TRUE, migrate_data => TRUE)"))
            return "hypertable"
    except Exception as e:  # noqa: BLE001
        log.warning("hypertable check skipped: %s", e)
        return "plain"
