"""Time-series storage, history (bucketed), energy integration (trapezoid), today summary, outages."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.drivers.base import NUMERIC_METRICS
from app.errors import err
from app.models import Device, Reading

BUCKET_SECONDS = {"raw": 0, "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}
BUCKET_ORDER = ["raw", "1m", "5m", "15m", "1h", "1d"]
HISTORY_METRICS = set(NUMERIC_METRICS) | {"grid_available"}
MAX_POINTS = 5000
GAP_SECONDS = 15 * 60  # segments longer than this are treated as data gaps (not integrated)
LOW_SOC_FLOOR = 20.0


async def store_reading(db: AsyncSession, device_id: uuid.UUID, ts: datetime, metrics: dict[str, Any],
                        raw: dict[str, Any]) -> None:
    stmt = insert(Reading).values(device_id=device_id, ts=ts, metrics=metrics, raw=raw).on_conflict_do_nothing()
    await db.execute(stmt)


def _expr(metric: str) -> str:
    if metric not in HISTORY_METRICS:  # whitelist => safe to interpolate
        raise err(400, "bad_request", f"unknown metric '{metric}'")
    if metric == "grid_available":
        return "(CASE WHEN metrics->>'grid_available' = 'true' THEN 1.0 WHEN metrics->>'grid_available' = 'false' THEN 0.0 END)"
    return f"((metrics->>'{metric}')::float)"


def parse_range(frm: datetime | None, to: datetime | None, max_days: int, default_hours: int = 24) -> tuple[datetime, datetime]:
    now = clock.utcnow()
    to = to or now
    frm = frm or (to - timedelta(hours=default_hours))
    if frm.tzinfo is None:
        frm = frm.replace(tzinfo=now.tzinfo)
    if to.tzinfo is None:
        to = to.replace(tzinfo=now.tzinfo)
    earliest = now - timedelta(days=max_days)
    frm = max(frm, earliest)  # clamp to plan history
    if to < frm:
        to = frm
    return frm, to


async def history(db: AsyncSession, device_id: uuid.UUID, tz: str, frm: datetime, to: datetime,
                  metrics: list[str], bucket: str, poll_interval: int = 15) -> dict[str, Any]:
    if bucket not in BUCKET_SECONDS:
        raise err(400, "bad_request", f"bucket must be one of {', '.join(BUCKET_ORDER)}")
    for m in metrics:
        _expr(m)
    span = max(1.0, (to - frm).total_seconds())
    # auto-coarsen so a request never returns an absurd number of points; the response says which bucket was used
    idx = BUCKET_ORDER.index(bucket)
    while idx < len(BUCKET_ORDER) - 1:
        step = BUCKET_SECONDS[BUCKET_ORDER[idx]] or poll_interval
        if span / step <= MAX_POINTS:
            break
        idx += 1
    bucket = BUCKET_ORDER[idx]
    cols = ", ".join(f"{_expr(m)} AS m{i}" for i, m in enumerate(metrics))
    params: dict[str, Any] = {"d": device_id, "f": frm, "t": to}
    if bucket == "raw":
        sql = f"SELECT ts AS b, {cols} FROM readings WHERE device_id=:d AND ts>=:f AND ts<=:t ORDER BY ts"
    elif bucket == "1d":
        params["tz"] = tz
        agg = ", ".join(f"avg({_expr(m)}) AS m{i}" for i, m in enumerate(metrics))
        sql = (f"SELECT (date_trunc('day', ts AT TIME ZONE CAST(:tz AS text)) AT TIME ZONE CAST(:tz AS text)) AS b, {agg} "
               f"FROM readings WHERE device_id=:d AND ts>=:f AND ts<=:t GROUP BY b ORDER BY b")
    else:
        params["s"] = BUCKET_SECONDS[bucket]
        agg = ", ".join(f"avg({_expr(m)}) AS m{i}" for i, m in enumerate(metrics))
        sql = (f"SELECT to_timestamp(floor(extract(epoch from ts)/CAST(:s AS integer))*CAST(:s AS integer)) AS b, {agg} FROM readings "
               f"WHERE device_id=:d AND ts>=:f AND ts<=:t GROUP BY b ORDER BY b")
    rows = (await db.execute(text(sql), params)).all()
    series: dict[str, list[list[Any]]] = {m: [] for m in metrics}
    for r in rows:
        ts = r[0].astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")
        for i, m in enumerate(metrics):
            v = r[i + 1]
            if v is not None:
                series[m].append([ts, round(float(v), 3)])
    return {"bucket": bucket, "series": series}


_INTEGRATE_SQL = """
WITH s AS (
  SELECT ts,
    COALESCE((metrics->>'pv_power')::float, 0) AS pv,
    COALESCE((metrics->>'load_power')::float, 0) AS ld,
    COALESCE((metrics->>'grid_power')::float,
      CASE WHEN metrics->>'grid_available' = 'true' AND COALESCE(metrics->>'mode','') IN ('line','bypass')
           THEN COALESCE((metrics->>'load_power')::float, 0) ELSE 0 END) AS gr
  FROM readings WHERE device_id = :d AND ts >= :f AND ts < :t
), w AS (
  SELECT ts, pv, ld, gr,
    lag(ts) OVER o AS pts, lag(pv) OVER o AS ppv, lag(ld) OVER o AS pld, lag(gr) OVER o AS pgr
  FROM s WINDOW o AS (ORDER BY ts)
)
SELECT (date_trunc('day', ts AT TIME ZONE CAST(:tz AS text)))::date AS d,
  COALESCE(SUM(CASE WHEN pts IS NOT NULL AND EXTRACT(EPOCH FROM ts - pts) <= CAST(:gap AS integer)
        THEN (pv + ppv) / 2 * EXTRACT(EPOCH FROM ts - pts) END), 0) / 3600000.0 AS pv_kwh,
  COALESCE(SUM(CASE WHEN pts IS NOT NULL AND EXTRACT(EPOCH FROM ts - pts) <= CAST(:gap AS integer)
        THEN (ld + pld) / 2 * EXTRACT(EPOCH FROM ts - pts) END), 0) / 3600000.0 AS load_kwh,
  COALESCE(SUM(CASE WHEN pts IS NOT NULL AND EXTRACT(EPOCH FROM ts - pts) <= CAST(:gap AS integer)
        THEN (gr + pgr) / 2 * EXTRACT(EPOCH FROM ts - pts) END), 0) / 3600000.0 AS grid_kwh
FROM w GROUP BY d ORDER BY d
"""


async def integrate_daily(db: AsyncSession, device_id: uuid.UUID, tz: str, frm: datetime, to: datetime) -> dict[str, dict[str, float]]:
    rows = (await db.execute(text(_INTEGRATE_SQL),
                             {"d": device_id, "f": frm, "t": to, "tz": tz, "gap": GAP_SECONDS})).all()
    return {r.d.isoformat(): {"pv_kwh": float(r.pv_kwh), "load_kwh": float(r.load_kwh), "grid_kwh": float(r.grid_kwh)}
            for r in rows}


def local_midnight(now: datetime, tz: str) -> datetime:
    z = ZoneInfo(tz)
    ln = now.astimezone(z)
    return ln.replace(hour=0, minute=0, second=0, microsecond=0)


async def energy_days(db: AsyncSession, device: Device, tz: str, days: int, max_days: int) -> list[dict[str, Any]]:
    now = clock.utcnow()
    days = max(1, min(days, max_days, 366))
    start = local_midnight(now, tz) - timedelta(days=days - 1)
    per_day = await integrate_daily(db, device.id, tz, start, now + timedelta(seconds=1))
    out = []
    for i in range(days):
        d = (start + timedelta(days=i)).date().isoformat()
        v = per_day.get(d, {"pv_kwh": 0.0, "load_kwh": 0.0, "grid_kwh": 0.0})
        out.append({"date": d, "pv_kwh": round(v["pv_kwh"], 3), "load_kwh": round(v["load_kwh"], 3),
                    "grid_kwh": round(v["grid_kwh"], 3)})
    return out


_TRANSITIONS_SQL = """
SELECT ts, ga FROM (
  SELECT ts, (metrics->>'grid_available') = 'true' AS ga,
         lag((metrics->>'grid_available') = 'true') OVER (ORDER BY ts) AS pga
  FROM readings WHERE device_id = :d AND ts >= :f AND ts < :t AND metrics->>'grid_available' IS NOT NULL
) x WHERE pga IS NULL OR pga <> ga ORDER BY ts
"""


async def grid_outages(db: AsyncSession, device_id: uuid.UUID, frm: datetime, to: datetime) -> list[dict[str, Any]]:
    rows = (await db.execute(text(_TRANSITIONS_SQL), {"d": device_id, "f": frm, "t": to})).all()
    outages: list[dict[str, Any]] = []
    start: datetime | None = None
    for i, r in enumerate(rows):
        if not r.ga and start is None:
            start = r.ts
            if i == 0:  # outage already running at range start: use the last time the grid was seen
                prev = (await db.execute(text(
                    "SELECT max(ts) FROM readings WHERE device_id=:d AND ts < :f AND ts >= :lb "
                    "AND metrics->>'grid_available' = 'true'"), {"d": device_id, "f": frm, "lb": frm - timedelta(days=2)})
                        ).scalar()
                if prev is not None:
                    start = prev
        elif r.ga and start is not None:
            outages.append({"from": start, "to": r.ts})
            start = None
    if start is not None:
        outages.append({"from": start, "to": None})
    return [{"from": o["from"].isoformat(), "to": o["to"].isoformat() if o["to"] else None} for o in outages]


def battery_runtime_hours(metrics: dict[str, Any] | None, capacity_wh: float) -> float | None:
    """(soc - 20%) x nominal capacity / load power."""
    if not metrics:
        return None
    soc, load = metrics.get("battery_soc"), metrics.get("load_power")
    if soc is None or load is None or load <= 10:
        return None
    usable = max(0.0, soc - LOW_SOC_FLOOR) / 100.0 * capacity_wh
    return round(usable / load, 2)


async def today_summary(db: AsyncSession, device: Device, tz: str) -> dict[str, Any]:
    now = clock.utcnow()
    start = local_midnight(now, tz)
    per_day = await integrate_daily(db, device.id, tz, start, now + timedelta(seconds=1))
    v = per_day.get(start.date().isoformat(), {"pv_kwh": 0.0, "load_kwh": 0.0, "grid_kwh": 0.0})
    outages = await grid_outages(db, device.id, start, now + timedelta(seconds=1))
    return {"pv_kwh": round(v["pv_kwh"], 3), "load_kwh": round(v["load_kwh"], 3), "grid_kwh": round(v["grid_kwh"], 3),
            "grid_outages": outages, "battery_runtime_hours": battery_runtime_hours(device.last_metrics, device.battery_capacity_wh)}
