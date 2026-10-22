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


async def _safe_ips(url: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address] | None:
    """Resolve the URL's host once; None unless every address is public (or ALLOW_PRIVATE_URLS)."""
    try:
        u = urlparse(url)
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or not u.hostname:
        return None
    host = u.hostname
    if not settings.allow_private_urls and (
            host.lower() in ("localhost",) or host.lower().endswith((".local", ".internal", ".localhost"))):
        return None
    try:
        ips = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
            ips = [ipaddress.ip_address(i[4][0]) for i in infos]
        except (OSError, ValueError):
            return None if not settings.allow_private_urls else []
    if settings.allow_private_urls:
        return ips
    return ips if ips and all(ip.is_global for ip in ips) else None


async def is_safe_url(url: str) -> bool:
    """SSRF guard: only http(s) to public addresses (unless ALLOW_PRIVATE_URLS)."""
    return await _safe_ips(url) is not None


async def safe_request(method: str, url: str, timeout: float, **kw: Any) -> httpx.Response:
    """Send to the address that passed the SSRF check (no second DNS lookup, so no DNS rebinding).
    The original host still goes in the Host header and TLS SNI/certificate check."""
    ips = await _safe_ips(url)
    if ips is None:
        raise ValueError("URL is not allowed")
    u = urlparse(url)
    ext: dict[str, Any] = {}
    target = url
    if ips:
        ip = ips[0]
        hostport = f"[{ip}]" if ip.version == 6 else str(ip)
        if u.port:
            hostport += f":{u.port}"
        target = u._replace(netloc=hostport).geturl()
        kw["headers"] = {**kw.get("headers", {}), "Host": u.netloc.rsplit("@", 1)[-1]}
        if u.scheme == "https":
            ext["sni_hostname"] = u.hostname
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as c:
        return await c.request(method, target, extensions=ext, **kw)


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
        try:
            r = await safe_request("POST", url, 10, json=payload)
            return r.status_code < 400
        except ValueError:
            log.warning("blocked unsafe webhook url %s", url)
            return False
        except httpx.HTTPError as e:
            log.warning("webhook error: %s", e)
            return False

    async def http_action(self, method: str, url: str, body: Any) -> bool:
        kw: dict[str, Any] = {}
        if body is not None and method != "GET":
            kw["json" if isinstance(body, (dict, list)) else "content"] = body
        r = await safe_request(method, url, 8, **kw)
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
