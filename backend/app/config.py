"""Application settings (environment variables / .env)."""
from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

VERSION = "0.1.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    app_env: str = "development"  # development | test | production
    database_url: str = "postgresql+asyncpg://se:se@localhost:5432/syriana_energy"
    redis_url: str = ""
    jwt_secret: str = "dev-insecure-secret-change-me-please-0123456789"
    credentials_key: str = ""
    public_base_url: str = "http://localhost:3000"
    cookie_secure: bool = False
    superadmin_email: str = ""

    telegram_bot_token: str = ""
    telegram_bot_username: str = "SyrianaEnergyBot"
    telegram_webhook_secret: str = ""

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "Syriana Energy <no-reply@syriana.energy>"
    smtp_starttls: bool = True

    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_model: str = "claude-sonnet-5-5"

    odoo_webhook_secret: str = ""
    shinemonitor_base: str = "http://android.shinemonitor.com/public/"

    allow_private_urls: bool = False  # SSRF guard for webhooks / automation http actions
    register_rate_limit: int = 30  # signups per IP per hour (raise for load/E2E tests)
    login_rate_limit: int = 8  # failed logins per window
    login_rate_window: int = 300  # seconds

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_default(cls, v: str) -> str:
        # an empty JWT_SECRET (e.g. `JWT_SECRET=` copied from .env.example) falls back to the dev default;
        # validate_production() rejects that default when APP_ENV=production.
        return v or "dev-insecure-secret-change-me-please-0123456789"

    @field_validator("database_url")
    @classmethod
    def _async_url(cls, v: str) -> str:
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            v = "postgresql+asyncpg://" + v[len("postgresql://"):]
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def validate_production(self) -> None:
        if not self.is_production:
            return
        problems = []
        if self.jwt_secret.startswith("dev-insecure") or len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET must be set to a random string of at least 32 chars")
        if not self.credentials_key:
            problems.append("CREDENTIALS_KEY must be set (Fernet key)")
        if problems:
            raise RuntimeError("Insecure production configuration: " + "; ".join(problems))


settings = Settings()
