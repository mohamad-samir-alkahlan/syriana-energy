"""Driver plugin interface + normalized metrics helpers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

NUMERIC_METRICS = [
    "grid_voltage", "grid_frequency", "grid_power", "pv_voltage", "pv_current", "pv_power",
    "battery_voltage", "battery_soc", "battery_power", "battery_charge_current", "battery_discharge_current",
    "load_power", "load_apparent_power", "load_percent", "output_voltage", "output_frequency",
    "bus_voltage", "inverter_temperature", "energy_pv_today", "energy_pv_total", "energy_load_today",
]
BOOL_METRICS = ["grid_available"]
STR_METRICS = ["mode", "output_priority", "charger_priority"]
LIST_METRICS = ["fault_codes"]
ALL_METRICS = NUMERIC_METRICS + BOOL_METRICS + STR_METRICS + LIST_METRICS
MODES = {"line", "battery", "standby", "fault", "bypass", "off", "unknown"}


class DriverError(Exception):
    def __init__(self, message: str, code: str = "driver_error", err: int | str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.err = err


@dataclass
class DeviceContext:
    id: str
    external_id: str
    credentials: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)  # driver-private, persisted by the caller
    battery_capacity_wh: float = 4800.0
    timezone: str = "Asia/Damascus"
    serial: str | None = None
    model: str | None = None
    name: str = ""


@dataclass
class Discovered:
    external_id: str
    name: str
    model: str | None = None
    serial: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"external_id": self.external_id, "name": self.name, "model": self.model, "serial": self.serial,
                "meta": self.meta}


@dataclass
class SettingDef:
    key: str
    label: str
    label_ar: str
    type: str  # enum | number | bool
    options: list[dict[str, str]] = field(default_factory=list)
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit: str | None = None
    value: Any = None
    group: str = "general"

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "label_ar": self.label_ar, "type": self.type,
                "options": self.options, "min": self.min, "max": self.max, "step": self.step, "unit": self.unit,
                "value": self.value, "group": self.group}

    def validate(self, value: Any) -> Any:
        """Return the normalized value or raise ValueError (-> 422 unsafe_value)."""
        if self.type == "bool":
            if isinstance(value, bool):
                return value
            raise ValueError(f"{self.key} must be true or false")
        if self.type == "enum":
            allowed = [o["value"] for o in self.options]
            if isinstance(value, bool) or str(value) not in allowed:
                raise ValueError(f"{self.key} must be one of {allowed}")
            return str(value)
        # number
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            try:
                value = float(value)  # accept numeric strings
            except (TypeError, ValueError):
                raise ValueError(f"{self.key} must be a number")
        v = float(value)
        if v != v or v in (float("inf"), float("-inf")):
            raise ValueError(f"{self.key} must be a finite number")
        if self.min is None or self.max is None:
            raise ValueError(f"{self.key} has no known safe range; changes are blocked")
        if v < self.min or v > self.max:
            raise ValueError(f"{self.key} must be between {self.min} and {self.max}")
        if self.step:
            n = round((v - self.min) / self.step)
            if abs(self.min + n * self.step - v) > 1e-6:
                raise ValueError(f"{self.key} must be a multiple of {self.step} starting at {self.min}")
        return int(v) if float(v).is_integer() and (self.step is None or float(self.step).is_integer()) else v


def clean_metrics(m: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in ALL_METRICS:
        v = m.get(k)
        if v is None:
            continue
        if k in NUMERIC_METRICS:
            try:
                out[k] = round(float(v), 3)
            except (TypeError, ValueError):
                continue
        elif k in BOOL_METRICS:
            out[k] = bool(v)
        elif k == "mode":
            out[k] = v if v in MODES else "unknown"
        elif k in LIST_METRICS:
            out[k] = [str(x) for x in v]
        else:
            out[k] = str(v)
    return out


class Driver(ABC):
    code: str
    name: str
    name_ar: str
    kind: str = "inverter"
    poll_interval: int = 60  # seconds
    credential_fields: list[dict[str, Any]] = []
    supports_control: bool = False
    supports_discovery: bool = True

    def info(self) -> dict[str, Any]:
        return {"code": self.code, "name": self.name, "name_ar": self.name_ar, "kind": self.kind,
                "credential_fields": self.credential_fields, "supports_control": self.supports_control,
                "supports_discovery": self.supports_discovery}

    @abstractmethod
    async def discover(self, credentials: dict[str, Any]) -> list[Discovered]: ...

    @abstractmethod
    async def read(self, device: DeviceContext) -> tuple[dict[str, Any], dict[str, Any]]:
        """Returns (normalized Metrics, raw vendor fields)."""

    async def get_settings(self, device: DeviceContext) -> list[SettingDef]:
        return []

    async def write_setting(self, device: DeviceContext, key: str, value: Any) -> None:
        raise DriverError("This driver does not support control", code="not_supported")

    def identify(self, external_id: str) -> tuple[str | None, str | None]:
        """(model, serial) derivable from external_id without network."""
        return None, None
