from __future__ import annotations

import secrets
import uuid
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.cache import limiter
from app.config import settings
from app.db import get_db
from app.deps import COOKIE, Principal, current_principal, parse_uuid, role_in_tenant, user_only
from app.errors import err
from app.models import AuthSession, Membership, Tenant, User
from app.security import (DUMMY_HASH, SESSION_DAYS, create_jwt, decrypt_str, encrypt_str, hash_password_async,
                          new_totp_secret, totp_url, verify_password_async, verify_totp)
from app.services import control
from app.services.tenants import create_tenant, tenant_out

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    tenant_name: str = Field(min_length=1, max_length=200)
    locale: Literal["ar", "en"] = "ar"


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=256)
    totp_code: str | None = None


class SwitchIn(BaseModel):
    tenant_id: str


class CodeIn(BaseModel):
    code: str


class PatchMeIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    locale: Literal["ar", "en"] | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
    current_password: str | None = None


def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def user_out(u: User) -> dict:
    return {"id": str(u.id), "email": u.email, "name": u.name, "locale": u.locale, "is_superadmin": u.is_superadmin,
            "totp_enabled": u.totp_enabled}


async def me_out(db: AsyncSession, user: User, tenant: Tenant, role: str) -> dict:
    rows = (await db.execute(select(Tenant, Membership.role).join(Membership, Membership.tenant_id == Tenant.id)
                             .where(Membership.user_id == user.id).order_by(Tenant.created_at))).all()
    tenants = [{"id": str(t.id), "name": t.name, "role": r} for t, r in rows]
    # installer owners/admins can switch into their customers' tenants
    parent_ids = [t.id for t, r in rows if t.type == "installer" and r in ("owner", "admin")]
    if parent_ids:
        kids = (await db.execute(select(Tenant).where(Tenant.parent_id.in_(parent_ids)).order_by(Tenant.created_at))).scalars()
        tenants += [{"id": str(k.id), "name": k.name, "role": "admin"} for k in kids]
    return {"user": user_out(user), "tenant": await tenant_out(db, tenant), "role": role, "tenants": tenants}


async def start_session(db: AsyncSession, response: Response, user: User, tenant: Tenant) -> None:
    jti = uuid.uuid4().hex
    token, exp = create_jwt(user.id, jti)
    db.add(AuthSession(jti=jti, user_id=user.id, tenant_id=tenant.id, expires_at=exp))
    await db.flush()
    response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=settings.cookie_secure, path="/")


@router.post("/register", status_code=201)
async def register(body: RegisterIn, request: Request, response: Response, db: AsyncSession = Depends(get_db, scope="function")):
    ip = client_ip(request)
    if await limiter.incr(f"register:{ip}", 3600) > settings.register_rate_limit:
        raise err(429, "rate_limited")
    email = body.email.lower()
    if (await db.execute(select(User.id).where(User.email == email))).first():
        raise err(409, "email_taken")
    user = User(email=email, name=body.name.strip(), password_hash=await hash_password_async(body.password), locale=body.locale)
    db.add(user)
    await db.flush()
    tenant = await create_tenant(db, body.tenant_name.strip(), "home", None, "free", body.locale)
    db.add(Membership(user_id=user.id, tenant_id=tenant.id, role="owner"))
    await db.flush()
    await start_session(db, response, user, tenant)
    await control.audit(db, None, "auth.register", email, tenant_id=tenant.id)
    return await me_out(db, user, tenant, "owner")


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db, scope="function")):
    ip = client_ip(request)
    email = body.email.lower()
    key, ip_key = f"login:{ip}:{email}", f"login-ip:{ip}"
    if await limiter.count(key) >= settings.login_rate_limit or await limiter.count(ip_key) >= settings.login_rate_limit * 5:
        raise err(429, "rate_limited")
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    ok = await verify_password_async(user.password_hash if user else DUMMY_HASH, body.password)
    if not user or not ok:
        await limiter.incr(key, settings.login_rate_window)
        await limiter.incr(ip_key, settings.login_rate_window)
        raise err(401, "invalid_credentials")
    if user.totp_enabled:
        if not body.totp_code:
            raise err(401, "totp_required")
        if not user.totp_secret_enc or not verify_totp(decrypt_str(user.totp_secret_enc), body.totp_code):
            await limiter.incr(key, settings.login_rate_window)
            raise err(401, "invalid_totp")
    await limiter.reset(key)
    m = (await db.execute(select(Tenant, Membership.role).join(Membership, Membership.tenant_id == Tenant.id)
                          .where(Membership.user_id == user.id).order_by(Tenant.created_at).limit(1))).first()
    if m is None:
        raise err(403, "forbidden", "User has no tenant")
    tenant, role = m
    await start_session(db, response, user, tenant)
    return await me_out(db, user, tenant, role)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db, scope="function")):
    from app.security import decode_jwt
    claims = decode_jwt(request.cookies.get(COOKIE, "")) if request.cookies.get(COOKIE) else None
    if claims:
        await db.execute(delete(AuthSession).where(AuthSession.jti == claims["jti"]))
    response.delete_cookie(COOKIE, path="/")
    response.status_code = 204
    return response


@router.get("/me")
async def me(p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    if p.user is None:
        raise err(403, "forbidden", "API keys cannot call /auth/me")
    return await me_out(db, p.user, p.tenant, p.role)


@router.post("/switch-tenant")
async def switch_tenant(body: SwitchIn, p: Principal = Depends(user_only), db: AsyncSession = Depends(get_db, scope="function")):
    target = await db.get(Tenant, parse_uuid(body.tenant_id))
    if target is None:
        raise err(404, "not_found")
    role = await role_in_tenant(db, p.user, target)
    if role is None:  # no existence leak
        raise err(404, "not_found")
    sess = await db.get(AuthSession, p.session_id)
    sess.tenant_id = target.id
    await control.audit(db, None, "auth.switch_tenant", str(target.id), {"from": str(p.tenant.id)}, tenant_id=target.id)
    return await me_out(db, p.user, target, role)


@router.post("/totp/setup")
async def totp_setup(p: Principal = Depends(user_only), db: AsyncSession = Depends(get_db, scope="function")):
    if p.user.totp_enabled:
        raise err(409, "conflict", "2FA is already enabled")
    secret = new_totp_secret()
    p.user.totp_secret_enc = encrypt_str(secret)
    return {"secret": secret, "otpauth_url": totp_url(secret, p.user.email)}


@router.post("/totp/enable")
async def totp_enable(body: CodeIn, p: Principal = Depends(user_only), db: AsyncSession = Depends(get_db, scope="function")):
    if not p.user.totp_secret_enc:
        raise err(400, "bad_request", "Call /totp/setup first")
    if not verify_totp(decrypt_str(p.user.totp_secret_enc), body.code):
        raise err(401, "invalid_totp")
    p.user.totp_enabled = True
    return {"ok": True, "totp_enabled": True}


@router.post("/totp/disable")
async def totp_disable(body: CodeIn, p: Principal = Depends(user_only), db: AsyncSession = Depends(get_db, scope="function")):
    if not p.user.totp_enabled or not p.user.totp_secret_enc:
        raise err(400, "bad_request", "2FA is not enabled")
    if not verify_totp(decrypt_str(p.user.totp_secret_enc), body.code):
        raise err(401, "invalid_totp")
    p.user.totp_enabled, p.user.totp_secret_enc = False, None
    return {"ok": True, "totp_enabled": False}


@router.patch("/me")
async def patch_me(body: PatchMeIn, p: Principal = Depends(user_only), db: AsyncSession = Depends(get_db, scope="function")):
    u = p.user
    if body.name is not None:
        u.name = body.name.strip()
    if body.locale is not None:
        u.locale = body.locale
    if body.password is not None:
        if not body.current_password or not await verify_password_async(u.password_hash, body.current_password):
            raise err(401, "invalid_credentials", "current_password is wrong")
        u.password_hash = await hash_password_async(body.password)
        await db.execute(delete(AuthSession).where(AuthSession.user_id == u.id, AuthSession.jti != p.session_id))
        await control.audit(db, None, "auth.password_change", str(u.id), tenant_id=p.tenant.id)
    return await me_out(db, u, p.tenant, p.role)
