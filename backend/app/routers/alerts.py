from __future__ import annotations

import hmac
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.config import settings
from app.db import get_db
from app.deps import Principal, current_principal, get_scoped, parse_uuid, require_roles
from app.errors import err
from app.models import Alert, AlertRule
from app.services import devices as dv
from app.services import notify, telegram
from app.services import control
from app.services.tenants import (DEFAULT_COOLDOWN, RULE_PARAM_DEFAULTS, RULE_TYPES, owner_locale)
from app import i18n

router = APIRouter(prefix="/api", tags=["alerts"])
WRITERS = ("owner", "admin")
CHANNELS = {"telegram", "email", "webhook", "inapp"}
PARAM_LIMITS = {"threshold_soc": (1, 100), "threshold_percent": (10, 150), "minutes": (1, 1440),
                "threshold_c": (30, 120), "hour_local": (0, 23)}


def rule_out(r: AlertRule) -> dict:
    return {"id": str(r.id), "type": r.type, "enabled": r.enabled, "params": r.params or {},
            "channels": r.channels or [], "cooldown_minutes": r.cooldown_minutes}


class RuleIn(BaseModel):
    type: str
    enabled: bool = True
    params: dict[str, Any] = Field(default_factory=dict)
    channels: list[str] | None = None
    cooldown_minutes: int | None = Field(default=None, ge=0, le=10080)


class RulePatch(BaseModel):
    enabled: bool | None = None
    params: dict[str, Any] | None = None
    channels: list[str] | None = None
    cooldown_minutes: int | None = Field(default=None, ge=0, le=10080)


def _clean_params(rtype: str, params: dict[str, Any]) -> dict[str, Any]:
    allowed = RULE_PARAM_DEFAULTS[rtype]
    out = dict(allowed)
    for k, v in params.items():
        if k not in allowed:
            raise err(422, "validation_error", f"Unknown parameter '{k}' for {rtype}")
        lo, hi = PARAM_LIMITS[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
            raise err(422, "validation_error", f"{k} must be a number between {lo} and {hi}")
        out[k] = v
    return out


def _check_channels(p: Principal, channels: list[str]) -> list[str]:
    bad = set(channels) - CHANNELS
    if bad:
        raise err(422, "validation_error", f"Unknown channels: {', '.join(sorted(bad))}")
    for ch in ("email", "webhook"):
        if ch in channels and ch not in p.plan.features:
            raise err(403, "feature_not_in_plan", feature=ch)
    return list(dict.fromkeys(channels))


@router.get("/alert-rules")
async def list_rules(p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    rows = (await db.execute(select(AlertRule).where(AlertRule.tenant_id == p.tenant.id).order_by(AlertRule.created_at, AlertRule.type))).scalars()
    return [rule_out(r) for r in rows]


@router.post("/alert-rules", status_code=201)
async def create_rule(body: RuleIn, p: Principal = Depends(require_roles(*WRITERS)), db: AsyncSession = Depends(get_db, scope="function")):
    if body.type not in RULE_TYPES:
        raise err(422, "validation_error", f"type must be one of {sorted(RULE_TYPES)}")
    r = AlertRule(tenant_id=p.tenant.id, type=body.type, enabled=body.enabled, params=_clean_params(body.type, body.params),
                  channels=_check_channels(p, body.channels if body.channels is not None else ["inapp", "telegram"]),
                  cooldown_minutes=body.cooldown_minutes if body.cooldown_minutes is not None else DEFAULT_COOLDOWN[body.type])
    db.add(r)
    await db.flush()
    return rule_out(r)


@router.patch("/alert-rules/{rid}")
async def patch_rule(rid: str, body: RulePatch, p: Principal = Depends(require_roles(*WRITERS)), db: AsyncSession = Depends(get_db, scope="function")):
    r = await get_scoped(db, AlertRule, rid, p.tenant.id)
    if body.enabled is not None:
        r.enabled = body.enabled
    if body.params is not None:
        r.params = _clean_params(r.type, {**(r.params or {}), **body.params})
    if body.channels is not None:
        r.channels = _check_channels(p, body.channels)
    if body.cooldown_minutes is not None:
        r.cooldown_minutes = body.cooldown_minutes
    return rule_out(r)


@router.delete("/alert-rules/{rid}", status_code=204)
async def delete_rule(rid: str, p: Principal = Depends(require_roles(*WRITERS)), db: AsyncSession = Depends(get_db, scope="function")):
    await db.delete(await get_scoped(db, AlertRule, rid, p.tenant.id))


# ------------------------------------------------------------------ alerts feed
@router.get("/alerts")
async def list_alerts(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), device_id: str | None = None,
                      p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    q = select(Alert).where(Alert.tenant_id == p.tenant.id)
    if device_id:
        q = q.where(Alert.device_id == parse_uuid(device_id))
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    unread = (await db.execute(select(func.count()).select_from(Alert).where(Alert.tenant_id == p.tenant.id, Alert.read.is_(False)))).scalar_one()
    rows = (await db.execute(q.order_by(Alert.created_at.desc()).limit(limit).offset(offset))).scalars().all()
    return {"items": [dv.alert_out(a) for a in rows], "total": total, "unread": unread}


@router.post("/alerts/read-all")
async def read_all(p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    res = await db.execute(update(Alert).where(Alert.tenant_id == p.tenant.id, Alert.read.is_(False)).values(read=True))
    return {"ok": True, "updated": res.rowcount}


@router.post("/alerts/{aid}/read")
async def read_one(aid: str, p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    a = await get_scoped(db, Alert, aid, p.tenant.id)
    a.read = True
    return dv.alert_out(a)


# ------------------------------------------------------------------ channels
def channels_out(t) -> dict:
    chats = t.telegram_chats or []
    em, wh = t.email_channel or {}, t.webhook_channel or {}
    return {"telegram": {"linked": bool(chats), "chat_title": ", ".join(c.get("title", "") for c in chats) or None,
                         "chats": [{"title": c.get("title"), "linked_at": c.get("linked_at")} for c in chats]},
            "email": {"enabled": bool(em.get("enabled")), "address": em.get("address")},
            "webhook": {"enabled": bool(wh.get("enabled")), "url": wh.get("url")}}


class EmailCh(BaseModel):
    enabled: bool | None = None
    address: str | None = Field(default=None, max_length=320)


class WebhookCh(BaseModel):
    enabled: bool | None = None
    url: str | None = Field(default=None, max_length=1000)


class ChannelsPatch(BaseModel):
    email: EmailCh | None = None
    webhook: WebhookCh | None = None


@router.get("/channels")
async def get_channels(p: Principal = Depends(current_principal)):
    return channels_out(p.tenant)


@router.patch("/channels")
async def patch_channels(body: ChannelsPatch, p: Principal = Depends(require_roles(*WRITERS)), db: AsyncSession = Depends(get_db, scope="function")):
    t = p.tenant
    if body.email is not None:
        if "email" not in p.plan.features:
            raise err(403, "feature_not_in_plan", feature="email")
        cur = dict(t.email_channel or {"enabled": False, "address": None})
        if body.email.address is not None:
            if body.email.address and "@" not in body.email.address:
                raise err(422, "validation_error", "Invalid email address")
            cur["address"] = body.email.address or None
        if body.email.enabled is not None:
            cur["enabled"] = body.email.enabled
        if cur["enabled"] and not cur.get("address"):
            raise err(422, "validation_error", "An address is required to enable email")
        t.email_channel = cur
    if body.webhook is not None:
        if "webhook" not in p.plan.features:
            raise err(403, "feature_not_in_plan", feature="webhook")
        cur = dict(t.webhook_channel or {"enabled": False, "url": None})
        if body.webhook.url is not None:
            if body.webhook.url and not await notify.is_safe_url(body.webhook.url):
                raise err(422, "unsafe_url")
            cur["url"] = body.webhook.url or None
        if body.webhook.enabled is not None:
            cur["enabled"] = body.webhook.enabled
        if cur["enabled"] and not cur.get("url"):
            raise err(422, "validation_error", "A URL is required to enable the webhook")
        t.webhook_channel = cur
    return channels_out(t)


@router.post("/channels/telegram/link")
async def telegram_link(p: Principal = Depends(require_roles(*WRITERS)), db: AsyncSession = Depends(get_db, scope="function")):
    code = await telegram.create_link_code(db, p.tenant.id, p.user.id if p.user else None)
    bot = settings.telegram_bot_username
    return {"code": code, "bot_username": bot, "deep_link": f"https://t.me/{bot}?start={code}"}


class TestIn(BaseModel):
    channel: Literal["telegram", "email", "webhook", "inapp"]


@router.post("/channels/test")
async def test_channel(body: TestIn, p: Principal = Depends(require_roles(*WRITERS)), db: AsyncSession = Depends(get_db, scope="function")):
    t = p.tenant
    lang = await owner_locale(db, t.id)
    msg = i18n.alert_message("test", {})
    alert = {"type": "test", "severity": "info", **msg, "device": None, "device_name": None, "tenant_id": str(t.id),
             "created_at": clock.utcnow().isoformat()}
    ch = body.channel
    if ch == "telegram" and not t.telegram_chats:
        raise err(400, "channel_not_configured")
    if ch == "email" and not ((t.email_channel or {}).get("enabled") and "email" in p.plan.features):
        raise err(400, "channel_not_configured")
    if ch == "webhook" and not ((t.webhook_channel or {}).get("enabled") and "webhook" in p.plan.features):
        raise err(400, "channel_not_configured")
    if ch == "inapp":
        db.add(Alert(tenant_id=t.id, type="test", severity="info", title=msg["title"], title_ar=msg["title_ar"],
                     body=msg["body"], body_ar=msg["body_ar"]))
        return {"ok": True, "channel": ch, "sent": 1}
    sent = await notify.dispatch(t, p.plan.features, alert, [ch], lang)
    n = sent.get(ch, 0)
    return {"ok": n > 0, "channel": ch, "sent": n}


@router.post("/telegram/webhook/{secret}")
async def telegram_webhook(secret: str, request: Request, db: AsyncSession = Depends(get_db, scope="function")):
    expected = settings.telegram_webhook_secret
    if not expected or not hmac.compare_digest(secret.encode(), expected.encode()):
        raise err(404, "not_found")
    try:
        update = await request.json()
    except ValueError:
        raise err(400, "bad_request", "invalid JSON")
    await telegram.handle_update(db, update)
    return {"ok": True}
