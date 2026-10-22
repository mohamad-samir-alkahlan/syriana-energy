from __future__ import annotations

from app.drivers.base import Driver

_REGISTRY: dict[str, Driver] = {}


def register(driver: Driver) -> Driver:
    _REGISTRY[driver.code] = driver
    return driver


def get_driver(code: str) -> Driver | None:
    _load()
    return _REGISTRY.get(code)


def all_drivers() -> list[Driver]:
    _load()
    return list(_REGISTRY.values())


_loaded = False


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    from app.drivers import demo, eybond_cloud  # noqa: F401  (import registers drivers)
