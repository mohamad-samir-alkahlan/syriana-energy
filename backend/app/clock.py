"""Overridable clock so tests and the demo driver are deterministic."""
from __future__ import annotations

from datetime import datetime, timezone

_override: datetime | None = None


def utcnow() -> datetime:
    return _override if _override is not None else datetime.now(timezone.utc)


def set_now(dt: datetime | None) -> None:
    global _override
    if dt is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _override = dt
