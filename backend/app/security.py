"""Password hashing, JWT, Fernet encryption, API keys, TOTP."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

_ph = PasswordHasher()
SESSION_DAYS = 7
API_KEY_PREFIX = "se_live_"


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(hashed: str, password: str) -> bool:
    try:
        return _ph.verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False


async def hash_password_async(password: str) -> str:
    """argon2 is CPU-heavy (~50ms): keep it off the event loop."""
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(hashed: str, password: str) -> bool:
    return await asyncio.to_thread(verify_password, hashed, password)


# Pre-computed hash used to equalize timing when the user does not exist.
DUMMY_HASH = hash_password("not-a-real-password")


def create_jwt(user_id: uuid.UUID, jti: str) -> tuple[str, datetime]:
    exp = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    token = jwt.encode({"sub": str(user_id), "jti": jti, "exp": exp, "iat": datetime.now(timezone.utc)},
                       settings.jwt_secret, algorithm="HS256")
    return token, exp


def decode_jwt(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], options={"require": ["exp", "sub", "jti"]})
    except jwt.PyJWTError:
        return None


@lru_cache(maxsize=4)
def _fernet_for(key: str, jwt_secret: str) -> Fernet:
    if key:
        try:
            return Fernet(key.encode())
        except (ValueError, TypeError):
            # any string is accepted: derive a valid Fernet key from it
            return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))
    # development fallback only (production validation forces CREDENTIALS_KEY)
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("cred:" + jwt_secret).encode()).digest()))


def fernet() -> Fernet:
    return _fernet_for(settings.credentials_key, settings.jwt_secret)


def encrypt_json(data: Any) -> str:
    return fernet().encrypt(json.dumps(data, separators=(",", ":")).encode()).decode()


def decrypt_json(token: str, ttl: int | None = None) -> Any:
    try:
        return json.loads(fernet().decrypt(token.encode(), ttl=ttl))
    except (InvalidToken, ValueError):
        raise ValueError("invalid token")


def encrypt_str(s: str) -> str:
    return fernet().encrypt(s.encode()).decode()


def decrypt_str(token: str) -> str:
    return fernet().decrypt(token.encode()).decode()


def generate_api_key() -> tuple[str, str, str]:
    """Returns (plaintext, display_prefix, sha256_hex). Only the hash is stored."""
    plain = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return plain, plain[:14], hash_api_key(plain)


def hash_api_key(plain: str) -> str:
    return hashlib.sha256(plain.encode()).hexdigest()


def new_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp(secret: str, code: str) -> bool:
    return bool(code) and pyotp.TOTP(secret).verify(code.strip().replace(" ", ""), valid_window=1)


def totp_url(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="Syriana Energy")
