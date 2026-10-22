# Syriana Energy · سيريانا إنرجي

منصة SaaS لمراقبة منظومات الطاقة الشمسية والتحكم بها: الإنفرتر، والبطارية لاحقاً، وأجهزة الشبكة لاحقاً.
تعمل بالعربي والإنجليزي، وتدعم العلامة البيضاء لشركات التركيب. فيها تنبيهات تلغرام وإيميل، ومساعد ذكي، و REST API، و MCP.

A white-label SaaS for monitoring and controlling solar systems (inverter now, lithium battery and network devices next).
Arabic + English, Telegram/email alerts, AI assistant, REST API and MCP.

## المكوّنات
| المجلد | ما فيه |
|---|---|
| `backend/` | FastAPI + PostgreSQL (TimescaleDB عند توفره) + Redis، والعامل (worker) الذي يقرأ الأجهزة ويطلق التنبيهات والقواعد الذكية، وخادم MCP على `/mcp` |
| `frontend/` | Next.js، عربي (RTL) وإنجليزي، ثيم فاتح وغامق، علامة بيضاء حسب الدومين، PWA |
| `e2e/` | اختبارات Playwright للنظام كاملاً (عربي وإنجليزي × كمبيوتر وموبايل) |
| `docs/` | الخطة، عقد الـ API، وتحليل بروتوكولات WatchPower و BMS |
| `design/` | نموذج التصميم المعتمد |

## التشغيل على السيرفر (Docker / Coolify)
```bash
cp .env.example .env
# عبّئ على الأقل: JWT_SECRET و CREDENTIALS_KEY و PUBLIC_BASE_URL
# CREDENTIALS_KEY: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
docker compose up -d --build
docker compose exec api python -m app.cli seed-plans
docker compose exec api python -m app.cli create-superadmin --email you@example.com --password '...'
docker compose exec api python -m app.cli seed-demo        # اختياري: حساب تجريبي
```
- الواجهة على المنفذ 3000. **لا تفتحها للعامة بدون HTTPS**: ضع أمامها Cloudflare أو Coolify proxy
  (الكوكي `Secure`)، واضبط `CLIENT_IP_HEADER` على ترويسة الـ IP الحقيقي (`cf-connecting-ip` خلف Cloudflare).
- على سيرفر devbox: `docker compose -f docker-compose.yml -f docker-compose.devbox.yml up -d --build` (energy.syriana.dev).
- التوثيق التفاعلي للـ API على `/api/docs` (مطفأ في الإنتاج إلا مع `API_DOCS=true`)، و MCP على `/mcp` (يحتاج مفتاح API).
- استعادة كلمة السر وتأكيد البريد تحتاجان `SMTP_*`.
- `BACKEND_URL` للواجهة يُثبَّت وقت البناء، والـ compose يمرّره تلقائياً.

## ربط إنفرتر WatchPower / SmartESS
من التطبيق: **الأجهزة ← إضافة جهاز ← WatchPower**، ثم تدخل اسم المستخدم وكلمة السر، فتظهر أجهزتك وتختار منها.
للتحقق من استجابات السيرفر الصيني الحقيقية: `python -m app.tools.shinemonitor_probe --user U --password P --out probe.json`.
هذه الأداة للقراءة فقط ولا ترسل أي أمر تحكم.

## التنبيهات
- **تلغرام:** أنشئ بوتاً من @BotFather، ثم ضع `TELEGRAM_BOT_TOKEN` و `TELEGRAM_BOT_USERNAME`. الزبون يربط حسابه بزر واحد من الإعدادات.
- **إيميل:** متغيرات `SMTP_*`.
- **المساعد الذكي:** `ANTHROPIC_API_KEY`، ويمكن تمريره عبر Cloudflare AI Gateway بـ `ANTHROPIC_BASE_URL`.
- **الفوترة من أودو:** webhook على `POST /api/billing/odoo/webhook` مع `ODOO_WEBHOOK_SECRET`.

## التطوير والاختبارات
```bash
cd backend && pip install -r requirements-dev.txt && alembic upgrade head && python -m pytest -q   # 116 اختبار
cd frontend && npm ci && npm run build && npm run lint
# اختبارات النظام كاملاً: انظر e2e/README.md (78 اختبار)
```

## ما لم يُجرَّب بعد على الواقع
- الاتصال بسيرفر ShineMonitor ما زال `http` (غير مشفّر)؛ مؤجَّل حتى نقرّر توجيهه عبر سيرفراتنا.
- الاتصال بسيرفر ShineMonitor بحساب حقيقي. التوقيع وأسماء الأوامر مأخوذة من التطبيق نفسه، لكن شكل بعض الردود مفترض، وأداة الـ probe موجودة للتحقق منه.
- بوت تلغرام الحقيقي، و SMTP، ومفتاح Claude، و TimescaleDB، و Docker. كلها مختبرة بمحاكاة فقط.
