"""Uniform error format: {"error": {"code","message","message_ar"}}."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

CATALOG: dict[str, tuple[str, str]] = {
    "unauthorized": ("Authentication required", "يلزم تسجيل الدخول"),
    "invalid_credentials": ("Invalid email or password", "البريد أو كلمة السر غير صحيحة"),
    "totp_required": ("Two-factor code required", "يلزم رمز التحقق بخطوتين"),
    "invalid_totp": ("Invalid two-factor code", "رمز التحقق غير صحيح"),
    "rate_limited": ("Too many attempts, try again later", "محاولات كثيرة، حاول لاحقاً"),
    "forbidden": ("You do not have permission", "لا تملك الصلاحية"),
    "feature_not_in_plan": ("This feature is not included in your plan", "هذه الميزة غير متوفرة في باقتك"),
    "plan_limit": ("Your plan's device limit has been reached", "وصلت للحد الأقصى للأجهزة في باقتك"),
    "not_found": ("Not found", "غير موجود"),
    "email_taken": ("Email already registered", "البريد مسجّل مسبقاً"),
    "invalid_token": ("This link is invalid or has expired", "الرابط غير صالح أو منتهي الصلاحية"),
    "validation_error": ("Invalid request", "طلب غير صالح"),
    "confirm_required": ("Confirmation required: send confirm=true", "يلزم التأكيد: أرسل confirm=true"),
    "unsafe_value": ("Value is outside the safe range", "القيمة خارج الحدود الآمنة"),
    "setting_not_found": ("Unknown setting", "إعداد غير معروف"),
    "ai_unavailable": ("AI assistant is not configured", "المساعد الذكي غير مفعّل"),
    "tenant_suspended": ("This account is suspended", "هذا الحساب معلّق"),
    "device_error": ("The device or its cloud returned an error", "الجهاز أو سحابته أعادت خطأ"),
    "device_exists": ("Device already added", "الجهاز مضاف مسبقاً"),
    "site_not_empty": ("Site still has devices", "الموقع فيه أجهزة"),
    "integration_token_invalid": ("Integration token is invalid or expired", "رمز الربط غير صالح أو منتهٍ"),
    "channel_not_configured": ("Channel is not configured", "القناة غير مهيأة"),
    "unknown_driver": ("Unknown driver", "نوع جهاز غير معروف"),
    "unknown_plan": ("Unknown plan", "باقة غير معروفة"),
    "invalid_secret": ("Invalid webhook secret", "سر الـ webhook غير صحيح"),
    "billing_not_configured": ("Billing webhook is not configured", "ربط الفوترة غير مفعّل"),
    "last_owner": ("A tenant must keep at least one owner", "يجب أن يبقى مالك واحد على الأقل"),
    "unsafe_url": ("URL is not allowed", "الرابط غير مسموح"),
    "integration_auth_failed": ("Login to the device cloud failed", "فشل تسجيل الدخول إلى سحابة الجهاز"),
    "ai_error": ("AI provider error", "خطأ من مزوّد الذكاء الاصطناعي"),
    "bad_request": ("Bad request", "طلب غير صحيح"),
    "conflict": ("Conflict", "تعارض"),
}


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str | None = None, message_ar: str | None = None,
                 extra: dict[str, Any] | None = None):
        en, ar = CATALOG.get(code, (code.replace("_", " "), code.replace("_", " ")))
        self.status = status
        self.code = code
        self.message = message or en
        self.message_ar = message_ar or (ar if message is None else ar)
        self.extra = extra or {}
        super().__init__(self.message)

    def body(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "message_ar": self.message_ar, **self.extra}}


def err(status: int, code: str, message: str | None = None, **extra: Any) -> AppError:
    return AppError(status, code, message, extra=extra or None)


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(exc.body(), status_code=exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "bad_request",
                429: "rate_limited"}.get(exc.status_code, "bad_request")
        e = AppError(exc.status_code, code, exc.detail if isinstance(exc.detail, str) and code == "bad_request" else None)
        return JSONResponse(e.body(), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        errs = []
        for e in exc.errors():
            loc = ".".join(str(x) for x in e.get("loc", []) if x != "body")
            errs.append(f"{loc}: {e.get('msg')}")
        e = AppError(422, "validation_error", "; ".join(errs)[:500] or None)
        return JSONResponse(e.body(), status_code=422)
