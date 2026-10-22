from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _pk():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _ts(**kw):
    return mapped_column(DateTime(timezone=True), server_default=func.now(), **kw)


def _fk(table: str, **kw):
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{table}.id", ondelete="CASCADE"), **kw)


class Plan(Base):
    __tablename__ = "plans"
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    name_ar: Mapped[str] = mapped_column(String(100))
    price_month: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_year: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    max_devices: Mapped[int] = mapped_column(Integer)
    history_days: Mapped[int] = mapped_column(Integer)
    features: Mapped[list[str]] = mapped_column(JSONB, default=list)
    per_device: Mapped[bool] = mapped_column(Boolean, default=False)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(16), default="home")  # home | installer
    parent_id: Mapped[uuid.UUID | None] = _fk("tenants", nullable=True, index=True)
    plan_code: Mapped[str] = mapped_column(ForeignKey("plans.code"), default="free")
    plan_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    custom_domain: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    branding: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Damascus")
    suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    telegram_chats: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    email_channel: Mapped[dict[str, Any]] = mapped_column(JSONB, default=lambda: {"enabled": False, "address": None})
    webhook_channel: Mapped[dict[str, Any]] = mapped_column(JSONB, default=lambda: {"enabled": False, "url": None})
    created_at: Mapped[datetime] = _ts()
    plan: Mapped[Plan] = relationship(lazy="joined")


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    locale: Mapped[str] = mapped_column(String(8), default="ar")
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _ts()


class Membership(Base):
    __tablename__ = "memberships"
    user_id: Mapped[uuid.UUID] = _fk("users", primary_key=True)
    tenant_id: Mapped[uuid.UUID] = _fk("tenants", primary_key=True)
    role: Mapped[str] = mapped_column(String(16), default="viewer")  # owner | admin | viewer


class AuthSession(Base):
    __tablename__ = "sessions"
    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = _fk("users", index=True)
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    created_at: Mapped[datetime] = _ts()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Site(Base):
    __tablename__ = "sites"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _fk("tenants", index=True)
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Damascus")
    created_at: Mapped[datetime] = _ts()


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("tenant_id", "driver", "external_id", name="uq_device_external"),)
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _fk("tenants", index=True)
    site_id: Mapped[uuid.UUID] = _fk("sites", index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16), default="inverter")
    driver: Mapped[str] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    serial: Mapped[str | None] = mapped_column(String(100), nullable=True)
    external_id: Mapped[str] = mapped_column(String(300))
    credentials_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    battery_capacity_wh: Mapped[float] = mapped_column(Float, default=4800.0)  # 24V x 200Ah
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # driver-private state
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    last_raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _ts()


class Reading(Base):
    """Time series. Becomes a TimescaleDB hypertable when the extension exists."""
    __tablename__ = "readings"
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"),
                                                 primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Command(Base):
    __tablename__ = "commands"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _fk("tenants", index=True)
    device_id: Mapped[uuid.UUID] = _fk("devices", index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    user_name: Mapped[str] = mapped_column(String(200), default="")
    source: Mapped[str] = mapped_column(String(16), default="rest")  # rest | mcp | automation
    key: Mapped[str] = mapped_column(String(100))
    old_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _ts()


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(String(200), nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _ts()


class AlertRule(Base):
    __tablename__ = "alert_rules"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _fk("tenants", index=True)
    type: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    channels: Mapped[list[str]] = mapped_column(JSONB, default=lambda: ["inapp", "telegram"])
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=30)
    created_at: Mapped[datetime] = _ts()


class AlertState(Base):
    """Per (rule, device) edge/cooldown state."""
    __tablename__ = "alert_state"
    rule_id: Mapped[uuid.UUID] = _fk("alert_rules", primary_key=True)
    device_id: Mapped[uuid.UUID] = _fk("devices", primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_tenant_created", "tenant_id", "created_at"),)
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    device_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL"),
                                                       nullable=True)
    device_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    type: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16), default="info")
    title: Mapped[str] = mapped_column(String(300))
    title_ar: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    body_ar: Mapped[str] = mapped_column(Text, default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _ts()


class Automation(Base):
    __tablename__ = "automations"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _fk("tenants", index=True)
    name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    device_id: Mapped[uuid.UUID | None] = _fk("devices", nullable=True)
    conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    grid: Mapped[str] = mapped_column(String(16), default="any")
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    recover_conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    recover_actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    state: Mapped[str] = mapped_column(String(16), default="idle")
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _ts()


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _fk("tenants", index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    prefix: Mapped[str] = mapped_column(String(24))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = _ts()
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TelegramLinkCode(Base):
    __tablename__ = "telegram_link_codes"
    code: Mapped[str] = mapped_column(String(12), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class BillingEvent(Base):
    __tablename__ = "billing_events"
    id: Mapped[uuid.UUID] = _pk()
    invoice_ref: Mapped[str] = mapped_column(String(200), unique=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _ts()


class KV(Base):
    __tablename__ = "kv"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=True)
