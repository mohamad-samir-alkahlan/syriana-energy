"""Telegram bot: account linking (/start CODE), /status, long-polling worker loop."""
from __future__ import annotations

import asyncio
import html
import logging
import secrets
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock, i18n
from app.config import settings
from app.models import KV, Tenant, TelegramLinkCode
from app.services import devices as dv
from app.services import notify
from app.services.tenants import owner_locale

log = logging.getLogger(__name__)
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_TTL_MIN = 15


async def create_link_code(db: AsyncSession, tenant_id, user_id) -> str:
    for _ in range(10):
        code = "".join(secrets.choice(ALPHABET) for _ in range(6))
        if await db.get(TelegramLinkCode, code) is None:
            db.add(TelegramLinkCode(code=code, tenant_id=tenant_id, user_id=user_id,
                                    expires_at=clock.utcnow() + timedelta(minutes=CODE_TTL_MIN), used=False))
            await db.flush()
            return code
    raise RuntimeError("could not allocate code")


def _chat_title(chat: dict[str, Any]) -> str:
    return (chat.get("title") or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x)
            or chat.get("username") or str(chat.get("id")))


async def tenant_for_chat(db: AsyncSession, chat_id: int) -> Tenant | None:
    return (await db.execute(select(Tenant).where(Tenant.telegram_chats.contains([{"chat_id": chat_id}])).limit(1))
            ).scalar_one_or_none()


async def status_text(db: AsyncSession, tenant: Tenant, lang: str) -> str:
    devices = (await dv.list_devices(db, tenant.id))[:6]
    if not devices:
        return i18n.bot("no_devices", lang)
    lines = []
    for d in devices:
        m = d.last_metrics or {}
        online = dv.is_online(d)
        grid = m.get("grid_available")
        if lang == "ar":
            parts = [f"<b>{html.escape(d.name)}</b> - " + ("متصل" if online else "غير متصل")]
            if m.get("battery_soc") is not None:
                parts.append(f"البطارية: {m['battery_soc']:.0f}%")
            if m.get("pv_power") is not None:
                parts.append(f"الشمس: {m['pv_power']:.0f} واط")
            if m.get("load_power") is not None:
                parts.append(f"الحمل: {m['load_power']:.0f} واط")
            if grid is not None:
                parts.append("الدولة: " + ("موجودة" if grid else "مقطوعة"))
        else:
            parts = [f"<b>{html.escape(d.name)}</b> - " + ("online" if online else "offline")]
            if m.get("battery_soc") is not None:
                parts.append(f"Battery: {m['battery_soc']:.0f}%")
            if m.get("pv_power") is not None:
                parts.append(f"Solar: {m['pv_power']:.0f} W")
            if m.get("load_power") is not None:
                parts.append(f"Load: {m['load_power']:.0f} W")
            if grid is not None:
                parts.append("Grid: " + ("on" if grid else "off"))
        lines.append("\n".join(parts))
    return "\n\n".join(lines)


async def handle_update(db: AsyncSession, update: dict[str, Any]) -> None:
    msg = update.get("message") or update.get("edited_message")
    if not msg or "text" not in msg:
        return
    chat = msg["chat"]
    chat_id = chat["id"]
    text = msg["text"].strip()
    cmd, _, arg = text.partition(" ")
    cmd = cmd.split("@")[0].lower()
    send = notify.transports.telegram

    if cmd == "/start":
        code = arg.strip().upper()
        if not code:
            tenant = await tenant_for_chat(db, chat_id)
            await send(chat_id, i18n.bot_both("welcome") if tenant is None else i18n.bot_both("help"), False)
            return
        row = await db.get(TelegramLinkCode, code)
        if row is None or row.used or row.expires_at < clock.utcnow():
            await send(chat_id, i18n.bot_both("bad_code"), False)
            return
        tenant = await db.get(Tenant, row.tenant_id)
        if tenant is None:
            await send(chat_id, i18n.bot_both("bad_code"), False)
            return
        chats = list(tenant.telegram_chats or [])
        if not any(c.get("chat_id") == chat_id for c in chats):
            chats.append({"chat_id": chat_id, "title": _chat_title(chat), "linked_at": clock.utcnow().isoformat()})
            tenant.telegram_chats = chats
        row.used = True
        await db.flush()
        await send(chat_id, i18n.bot_both("linked", tenant=tenant.name), False)
        return

    tenant = await tenant_for_chat(db, chat_id)
    if cmd in ("/status", "/help"):
        if tenant is None:
            await send(chat_id, i18n.bot_both("not_linked"), False)
            return
        lang = await owner_locale(db, tenant.id)
        if cmd == "/status":
            await send(chat_id, await status_text(db, tenant, lang), True)
        else:
            await send(chat_id, i18n.bot("help", lang), False)


async def _get_offset(db: AsyncSession) -> int:
    row = await db.get(KV, "telegram_offset")
    return int(row.value) if row and row.value is not None else 0


async def _set_offset(db: AsyncSession, v: int) -> None:
    row = await db.get(KV, "telegram_offset")
    if row is None:
        db.add(KV(key="telegram_offset", value=v))
    else:
        row.value = v


async def poll_forever(session_factory, stop: asyncio.Event, transport: httpx.AsyncBaseTransport | None = None) -> None:
    """Long-polling getUpdates loop (worker). Exits when `stop` is set."""
    if not settings.telegram_bot_token:
        return
    base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
    log.info("telegram polling started")
    async with httpx.AsyncClient(timeout=httpx.Timeout(40.0), transport=transport) as client:
        while not stop.is_set():
            try:
                async with session_factory() as db:
                    offset = await _get_offset(db)
                r = await client.get(f"{base}/getUpdates", params={"offset": offset, "timeout": 25,
                                                                   "allowed_updates": '["message"]'})
                if r.status_code == 409:  # a webhook is configured for this bot
                    log.warning("telegram getUpdates 409 (webhook set?); retrying in 60s")
                    await asyncio.wait_for(stop.wait(), 60)
                    continue
                data = r.json()
                for upd in data.get("result", []):
                    async with session_factory() as db:
                        try:
                            await handle_update(db, upd)
                            await _set_offset(db, upd["update_id"] + 1)
                            await db.commit()
                        except Exception:  # noqa: BLE001
                            await db.rollback()
                            log.exception("telegram update failed")
                            async with session_factory() as db2:  # skip the poison update
                                await _set_offset(db2, upd["update_id"] + 1)
                                await db2.commit()
            except asyncio.TimeoutError:
                pass
            except (httpx.HTTPError, ValueError) as e:
                log.warning("telegram polling error: %s", e)
                try:
                    await asyncio.wait_for(stop.wait(), 5)
                except asyncio.TimeoutError:
                    pass
