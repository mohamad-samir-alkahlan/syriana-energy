"""Bilingual (en/ar) message templates for alerts and bot replies."""
from __future__ import annotations

from typing import Any


def fmt_duration(minutes: float, lang: str) -> str:
    m = int(round(minutes))
    h, mm = divmod(m, 60)
    if lang == "ar":
        if h and mm:
            return f"{h} س و{mm} د"
        return f"{h} س" if h else f"{mm} د"
    if h and mm:
        return f"{h}h {mm}m"
    return f"{h}h" if h else f"{mm}m"


def _f(x: Any, nd: int = 0) -> str:
    try:
        return f"{float(x):.{nd}f}"
    except (TypeError, ValueError):
        return "-"


def alert_message(kind: str, c: dict[str, Any]) -> dict[str, str]:
    d = c.get("device", "")
    if kind == "battery_low":
        return dict(
            title=f"Battery low ({_f(c.get('soc'))}%)", title_ar=f"البطارية منخفضة ({_f(c.get('soc'))}%)",
            body=f"{d}: battery dropped to {_f(c.get('soc'))}% (threshold {_f(c.get('threshold'))}%).",
            body_ar=f"{d}: انخفضت البطارية إلى {_f(c.get('soc'))}% (الحد {_f(c.get('threshold'))}%).")
    if kind == "battery_full":
        return dict(title="Battery full", title_ar="البطارية ممتلئة",
                    body=f"{d}: battery reached {_f(c.get('soc'))}%.",
                    body_ar=f"{d}: وصلت البطارية إلى {_f(c.get('soc'))}%.")
    if kind == "grid_lost":
        return dict(title="Grid power lost", title_ar="انقطعت كهرباء الدولة",
                    body=f"{d}: running on battery/solar. Battery {_f(c.get('soc'))}%.",
                    body_ar=f"{d}: يعمل على البطارية/الشمس. البطارية {_f(c.get('soc'))}%.")
    if kind == "grid_restored":
        mins = c.get("outage_minutes")
        mins = mins if mins is not None and mins >= 1 else None
        en = f"{d}: grid is back." + (f" Outage lasted {fmt_duration(mins, 'en')}." if mins else "")
        ar = f"{d}: رجعت الكهرباء." + (f" دام الانقطاع {fmt_duration(mins, 'ar')}." if mins else "")
        return dict(title="Grid power restored", title_ar="رجعت كهرباء الدولة", body=en, body_ar=ar)
    if kind == "overload":
        return dict(title=f"Overload ({_f(c.get('percent'))}%)", title_ar=f"حمل زائد ({_f(c.get('percent'))}%)",
                    body=f"{d}: load at {_f(c.get('percent'))}% for {_f(c.get('minutes'))} min (limit {_f(c.get('threshold'))}%).",
                    body_ar=f"{d}: الحمل {_f(c.get('percent'))}% منذ {_f(c.get('minutes'))} دقيقة (الحد {_f(c.get('threshold'))}%).")
    if kind == "fault":
        codes = ", ".join(c.get("codes") or []) or c.get("mode", "fault")
        return dict(title="Inverter fault", title_ar="عطل في الإنفرتر", body=f"{d}: {codes}", body_ar=f"{d}: {codes}")
    if kind == "device_offline":
        return dict(title="Device offline", title_ar="الجهاز غير متصل",
                    body=f"{d}: no data for {_f(c.get('minutes'))} minutes.",
                    body_ar=f"{d}: لا توجد بيانات منذ {_f(c.get('minutes'))} دقيقة.")
    if kind == "device_online":
        return dict(title="Device back online", title_ar="عاد الجهاز للاتصال", body=f"{d}: data is flowing again.",
                    body_ar=f"{d}: عادت البيانات.")
    if kind == "high_temperature":
        return dict(title=f"High temperature ({_f(c.get('temp'))}°C)",
                    title_ar=f"حرارة مرتفعة ({_f(c.get('temp'))}°م)",
                    body=f"{d}: inverter temperature {_f(c.get('temp'))}°C (limit {_f(c.get('threshold'))}°C).",
                    body_ar=f"{d}: حرارة الإنفرتر {_f(c.get('temp'))}°م (الحد {_f(c.get('threshold'))}°م).")
    if kind == "daily_summary":
        o = c.get("outages", 0)
        dur = c.get("outage_minutes") or 0
        return dict(
            title="Daily summary", title_ar="الملخص اليومي",
            body=f"{d}: solar {_f(c.get('pv'), 1)} kWh, load {_f(c.get('load'), 1)} kWh, grid {_f(c.get('grid'), 1)} kWh, "
                 f"outages {o}" + (f" ({fmt_duration(dur, 'en')})" if o else "") + ".",
            body_ar=f"{d}: الشمس {_f(c.get('pv'), 1)} ك.و.س، الاستهلاك {_f(c.get('load'), 1)} ك.و.س، "
                    f"الشبكة {_f(c.get('grid'), 1)} ك.و.س، الانقطاعات {o}" + (f" ({fmt_duration(dur, 'ar')})" if o else "") + ".")
    if kind == "automation":
        return dict(title=f"Automation: {c.get('name', '')}", title_ar=f"أتمتة: {c.get('name', '')}",
                    body=str(c.get("message") or ""), body_ar=str(c.get("message") or ""))
    if kind == "test":
        return dict(title="Test notification", title_ar="إشعار تجريبي",
                    body="Syriana Energy notifications are working.", body_ar="إشعارات سيريانا للطاقة تعمل بشكل سليم.")
    return dict(title=kind, title_ar=kind, body="", body_ar="")


SEVERITY = {"battery_low": "warning", "battery_full": "info", "grid_lost": "warning", "grid_restored": "info",
            "overload": "critical", "fault": "critical", "device_offline": "warning", "device_online": "info",
            "high_temperature": "warning", "daily_summary": "info", "automation": "info", "test": "info"}

BOT = {
    "welcome": {"ar": "أهلاً بك في سيريانا للطاقة. أرسل /start الرمز لربط حسابك (الرمز من صفحة القنوات في التطبيق).",
                "en": "Welcome to Syriana Energy. Send /start CODE to link your account (get the code from the Channels page)."},
    "linked": {"ar": "تم ربط هذه المحادثة بحساب «{tenant}». ستصلك التنبيهات هنا. جرّب /status",
               "en": "This chat is now linked to \"{tenant}\". You will receive alerts here. Try /status"},
    "bad_code": {"ar": "الرمز غير صالح أو منتهي. اطلب رمزاً جديداً من التطبيق.",
                 "en": "The code is invalid or expired. Please request a new one in the app."},
    "not_linked": {"ar": "هذه المحادثة غير مربوطة بحساب. أرسل /start الرمز.",
                   "en": "This chat is not linked to an account. Send /start CODE."},
    "no_devices": {"ar": "لا توجد أجهزة مضافة بعد.", "en": "No devices yet."},
    "help": {"ar": "الأوامر:\n/status - الحالة الحالية\n/help - المساعدة",
             "en": "Commands:\n/status - current status\n/help - help"},
}


def bot(key: str, lang: str, **kw: Any) -> str:
    t = BOT[key]
    return (t["ar"] if lang == "ar" else t["en"]).format(**kw) + ("" if lang == "ar" else "") 


def bot_both(key: str, **kw: Any) -> str:
    return BOT[key]["ar"].format(**kw) + "\n\n" + BOT[key]["en"].format(**kw)
