"""Notification delivery: telegram / email / webhook (inapp is the Alert row itself)."""
from __future__ import annotations

import asyncio
import html
import ipaddress
import logging
import socket
from email.message import EmailMessage
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.models import Tenant

log = logging.getLogger(__name__)


async def is_safe_url(url: str) -> bool:
    """SSRF guard: only http(s) to public addresses (unless ALLOW_PRIVATE_URLS)."""
    try:
        u = urlparse(url)
    except ValueError:
        return False
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    if settings.allow_private_urls:
        return True
    host = u.hostname
    if host.lower() in ("localhost",) or host.lower().endswith((".local", ".internal", ".localhost")):
        return False
    try:
        ips = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
            ips = [ipaddress.ip_address(i[4][0]) for i in infos]
        except (OSError, ValueError):
            return False
    return bool(ips) and all(ip.is_global for ip in ips)


class Transports:
    """Network edge; tests replace the module-level instance with a recorder."""

    async def telegram(self, chat_id: int | str, text: str, html_mode: bool = True) -> bool:
        if not settings.telegram_bot_token:
            log.info("telegram not configured; dropping message to %s", chat_id)
            return False
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True}
        if html_mode:
            payload["parse_mode"] = "HTML"
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage", json=payload)
            if r.status_code != 200:
                log.warning("telegram sendMessage failed: %s %s", r.status_code, r.text[:200])
            return r.status_code == 200
        except httpx.HTTPError as e:
            log.warning("telegram error: %s", e)
            return False

    async def email(self, to: str, subject: str, body: str) -> bool:
        if not settings.smtp_host:
            log.info("smtp not configured; dropping email to %s", to)
            return False
        import aiosmtplib
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = settings.smtp_from, to, subject
        msg.set_content(body)
        try:
            await aiosmtplib.send(msg, hostname=settings.smtp_host, port=settings.smtp_port,
                                  username=settings.smtp_user or None, password=settings.smtp_password or None,
                                  start_tls=settings.smtp_starttls, timeout=15)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("smtp error: %s", e)
            return False

    async def webhook(self, url: str, payload: dict[str, Any]) -> bool:
        if not await is_safe_url(url):
            log.warning("blocked unsafe webhook url %s", url)
            return False
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as c:
                r = await c.post(url, json=payload)
            return r.status_code < 400
        except httpx.HTTPError as e:
            log.warning("webhook error: %s", e)
            return False

    async def http_action(self, method: str, url: str, body: Any) -> bool:
        if not await is_safe_url(url):
            raise ValueError("URL is not allowed")
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as c:
            kw: dict[str, Any] = {}
            if body is not None and method != "GET":
                kw["json" if isinstance(body, (dict, list)) else "content"] = body
            r = await c.request(method, url, **kw)
        if r.status_code >= 400:
            raise ValueError(f"HTTP {r.status_code}")
        return True


transports = Transports()


def telegram_text(alert: dict[str, Any], lang: str) -> str:
    title = alert["title_ar"] if lang == "ar" else alert["title"]
    body = alert["body_ar"] if lang == "ar" else alert["body"]
    icon = {"critical": "🔴", "warning": "🟠"}.get(alert.get("severity", ""), "🟢")
    return f"{icon} <b>{html.escape(title)}</b>\n{html.escape(body)}"


async def dispatch(tenant: Tenant, features: set[str], alert: dict[str, Any], channels: list[str], lang: str) -> dict[str, int]:
    """Send an alert through the external channels. Never raises. Returns {channel: sent_count}."""
    sent: dict[str, int] = {}
    if "telegram" in channels:
        n = 0
        for chat in tenant.telegram_chats or []:
            if await transports.telegram(chat["chat_id"], telegram_text(alert, lang)):
                n += 1
        sent["telegram"] = n
    em = tenant.email_channel or {}
    if "email" in channels and "email" in features and em.get("enabled") and em.get("address"):
        subj = alert["title_ar"] if lang == "ar" else alert["title"]
        body = alert["body_ar"] if lang == "ar" else alert["body"]
        sent["email"] = int(await transports.email(em["address"], f"[Syriana Energy] {subj}", f"{body}\n\n-- Syriana Energy"))
    wh = tenant.webhook_channel or {}
    if "webhook" in channels and "webhook" in features and wh.get("enabled") and wh.get("url"):
        sent["webhook"] = int(await transports.webhook(wh["url"], {"event": "alert", **alert}))
    return sent
