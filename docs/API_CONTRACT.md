# Syriana Energy — API Contract (v1)

This is the single source of truth between `backend/` (FastAPI) and `frontend/` (Next.js).
All endpoints are under `/api`. JSON in/out. Times are ISO-8601 UTC strings. Numbers are SI floats (W, V, A, Hz, %, kWh).

## Conventions
- **Auth (browser):** httpOnly cookie `se_session` (JWT HS256, 7 days, SameSite=Lax, Secure in prod). Frontend calls the API through a Next.js rewrite `/api/* -> ${BACKEND_URL}/api/*`, so the cookie is first-party and there is no CORS.
- **Auth (machines):** header `Authorization: Bearer se_live_xxx` (API key). The same keys are used for MCP.
- **Errors:** `{"error": {"code": "snake_case_code", "message": "human text (en)", "message_ar": "نص عربي"}}` with a proper HTTP status.
- **Tenant scoping:** every resource belongs to the caller's current tenant. Cross-tenant access returns 404.
- **Roles inside a tenant:** `owner`, `admin`, `viewer`. A user can also be platform `is_superadmin`.
- **Pagination:** `?limit=50&offset=0` and response `{"items": [...], "total": N}`.

## Normalized metrics (`Metrics` object)
Drivers map vendor data into these keys. Any key may be missing (null).
```
grid_voltage, grid_frequency, grid_power, grid_available (bool)
pv_voltage, pv_current, pv_power
battery_voltage, battery_soc, battery_power   (+ charging / - discharging, W)
battery_charge_current, battery_discharge_current
load_power, load_apparent_power, load_percent, output_voltage, output_frequency
bus_voltage, inverter_temperature
mode            enum: "line" | "battery" | "standby" | "fault" | "bypass" | "off" | "unknown"
output_priority enum string as reported (e.g. "USB","SUB","SBU")
charger_priority enum string as reported
energy_pv_today, energy_pv_total, energy_load_today   (kWh)
fault_codes     list[str]
```
`LiveStatus = {"device_id", "ts", "online": bool, "metrics": Metrics, "raw": {...vendor fields...}}`

## Public
- `GET /api/health` → `{"ok": true, "version": "x.y.z"}`
- `GET /api/public/branding?host=energy.example.com` → `Branding`
  `Branding = {"name","name_ar","logo_url","primary_color","accent_color","support_email","powered_by": bool}`
  Resolution: a tenant with a matching `custom_domain`, otherwise the platform default ("Syriana Energy", primary `#DA7756`).
- `GET /api/public/plans` → list of `Plan`.

## Auth
- `POST /api/auth/register` `{email,password,name,tenant_name,locale:"ar"|"en"}` → 201 `Me`, and sets the cookie. Creates a tenant of type `home` with the user as `owner` on the `free` plan.
- `POST /api/auth/login` `{email,password,totp_code?}` → `Me` + cookie. If 2FA is enabled and the code is missing → 401 `{"error":{"code":"totp_required"}}`.
- `POST /api/auth/logout` → 204
- `GET /api/auth/me` → `Me`
  `Me = {"user":{"id","email","name","locale","is_superadmin","totp_enabled"},"tenant":Tenant,"role","tenants":[{"id","name","role"}]}`
- `POST /api/auth/switch-tenant` `{tenant_id}` → `Me` (installers switch into a customer tenant)
- `POST /api/auth/totp/setup` → `{"secret","otpauth_url"}`; `POST /api/auth/totp/enable` `{code}`; `POST /api/auth/totp/disable` `{code}`
- `PATCH /api/auth/me` `{name?,locale?,password?,current_password?}`

## Tenant / branding / plan
`Tenant = {"id","name","type":"home"|"installer","parent_id","plan":Plan,"plan_expires_at","branding":Branding,"custom_domain","timezone","created_at"}`
`Plan = {"code":"free"|"home"|"pro"|"installer","name","name_ar","price_month","price_year","currency":"USD","max_devices","history_days","features":["control","ai","email","webhook","automations","api","white_label","customers"]}`
- `GET /api/tenant` → `Tenant`; `PATCH /api/tenant` `{name?,timezone?}`
- `PATCH /api/tenant/branding` (requires the `white_label` feature) `{name,name_ar,logo_url,primary_color,accent_color,support_email,custom_domain}`
- `GET /api/tenant/usage` → `{"devices":n,"max_devices":n,"history_days":n}`

## Installer: customers (requires the `customers` feature)
- `GET /api/customers` → items of `{"id","name","devices","online","plan","created_at"}`
- `POST /api/customers` `{name, owner_email, owner_name, password?}` → creates a child tenant (it inherits the parent's branding) and its owner user.
- `DELETE /api/customers/{id}`

## Team
- `GET /api/users`, `POST /api/users` `{email,name,role,password}`, `PATCH /api/users/{id}` `{role}`, `DELETE /api/users/{id}`

## Sites & devices
`Site = {"id","name","timezone","devices":[Device]}`
`Device = {"id","site_id","name","kind":"inverter"|"battery"|"network","driver","model","serial","online","last_seen","last_metrics":Metrics|null,"created_at"}`
- `GET /api/sites`, `POST /api/sites` `{name}`, `PATCH /api/sites/{id}`, `DELETE /api/sites/{id}`
- `GET /api/drivers` → `[{"code","name","name_ar","kind","credential_fields":[{"key","label","label_ar","type":"text"|"password","required"}],"supports_control":bool,"supports_discovery":bool}]`
  Drivers: `eybond_cloud` (WatchPower / SmartESS / ShineMonitor account), `demo` (simulated 24V hybrid inverter).
- `POST /api/integrations/discover` `{driver, credentials:{...}}` → `{"integration_token", "devices":[{"external_id","name","model","serial","meta":{}}]}` (integration_token = encrypted, short-lived blob of the credentials)
- `POST /api/devices` `{site_id, driver, integration_token? , credentials?, external_id, name}` → `Device`. Credentials are stored encrypted (Fernet). The plan's `max_devices` is enforced (403 `plan_limit`).
- `GET /api/devices/{id}`, `PATCH /api/devices/{id}` `{name}`, `DELETE /api/devices/{id}`
- `GET /api/devices/{id}/live` → `LiveStatus` (from the latest stored reading; `online` = data newer than 3×poll interval)
- `GET /api/devices/{id}/history?from=&to=&metrics=pv_power,load_power,battery_soc&bucket=5m` → `{"bucket":"5m","series":{"pv_power":[[ts,value],...],...}}`. Allowed buckets: raw, 1m, 5m, 15m, 1h, 1d. The range is clamped to the plan's `history_days`.
- `GET /api/devices/{id}/energy?days=30` → `[{"date":"2026-10-22","pv_kwh","load_kwh","grid_kwh"}]` (integrated from the power series)
- `GET /api/devices/{id}/today` → `{"pv_kwh","load_kwh","grid_kwh","grid_outages":[{"from","to"}],"battery_runtime_hours": float|null}`

## Control (requires the `control` feature and the owner/admin role)
`Setting = {"key","label","label_ar","type":"enum"|"number"|"bool","options":[{"value","label","label_ar"}],"min","max","step","unit","value","group"}`
- `GET /api/devices/{id}/settings` → `[Setting]`
- `POST /api/devices/{id}/settings` `{key, value, confirm:true}` → `Command`. Without `confirm:true` → 400 `confirm_required`. Out-of-range → 422 `unsafe_value`.
- `GET /api/devices/{id}/commands` → items of `Command = {"id","key","old_value","new_value","status":"pending"|"ok"|"failed","error","user_name","created_at"}`

## Alerts & notifications
`AlertRule = {"id","type","enabled","params":{...},"channels":["telegram","email","webhook","inapp"],"cooldown_minutes"}`
Types and params:
- `battery_low` {threshold_soc:30} · `battery_full` {threshold_soc:100}
- `grid_lost` {} · `grid_restored` {}
- `overload` {threshold_percent:90, minutes:3}
- `fault` {} (mode=fault or fault_codes not empty)
- `device_offline` {minutes:10}
- `high_temperature` {threshold_c:60}
- `daily_summary` {hour_local:21}
- `GET /api/alert-rules` (default rules are seeded on tenant creation), `POST`, `PATCH /{id}`, `DELETE /{id}`
- `GET /api/alerts?limit=&offset=&device_id=` → items of `Alert = {"id","device_id","device_name","type","severity":"info"|"warning"|"critical","title","title_ar","body","body_ar","created_at","read":bool}`
- `POST /api/alerts/read-all`, `POST /api/alerts/{id}/read`

## Notification channels
- `GET /api/channels` → `{"telegram":{"linked":bool,"chat_title"},"email":{"enabled","address"},"webhook":{"enabled","url"}}`
- `POST /api/channels/telegram/link` → `{"code":"ABC123","bot_username","deep_link":"https://t.me/<bot>?start=ABC123"}`; the bot links the chat when it receives `/start ABC123` (webhook `POST /api/telegram/webhook/{secret}` or polling in the worker).
- `PATCH /api/channels` `{email:{enabled,address}, webhook:{enabled,url}}`
- `POST /api/channels/test` `{channel}` → sends a test message.

## Automations (load shedding; requires `automations`)
`Automation = {"id","name","enabled","device_id","conditions":[{"metric","op":"<"|">"|"<="|">="|"==","value"}],"grid":"any"|"available"|"lost","actions":[{"type":"notify","message"}|{"type":"http","method","url","body"}|{"type":"setting","key","value"}],"recover_conditions":[...],"recover_actions":[...],"state":"idle"|"active","last_triggered_at"}`
- CRUD at `/api/automations`. The worker evaluates them on every new reading, with hysteresis: it fires once on entering, and runs recover_actions once on leaving.

## AI assistant (requires `ai`)
- `POST /api/assistant/chat` `{"messages":[{"role":"user"|"assistant","content"}], "device_id"?}` → `{"reply": "...", "used_tools":[...]}`. The server calls Claude with tools (live status, today summary, history summary, alerts, settings). It answers in the user's language. Returns 503 `ai_unavailable` if no API key is configured.

## API keys (requires `api`)
- `GET /api/api-keys`, `POST /api/api-keys` `{name}` → `{"id","name","key"}` (the key is shown once), `DELETE /api/api-keys/{id}`

## MCP
- Streamable HTTP at `/mcp` (served by the backend), auth `Authorization: Bearer <api key>`.
- Tools: `list_devices`, `get_live_status(device_id)`, `get_today_summary(device_id)`, `get_history(device_id, metric, hours)`, `list_alerts(limit)`, `get_settings(device_id)`, `change_setting(device_id, key, value, confirm)`.

## Billing / Odoo
- `POST /api/billing/odoo/webhook` with header `X-Odoo-Secret: <ODOO_WEBHOOK_SECRET>` and body `{"tenant_id"|"email", "plan_code", "expires_at", "invoice_ref"}` → activates or renews the plan.
- When the plan expires, the worker downgrades the tenant to `free`.

## Platform admin (is_superadmin)
- `GET /api/admin/stats` → `{"tenants","users","devices","devices_online","by_plan":{code:n},"signups_30d":[[date,n]],"mrr_estimate"}`
- `GET /api/admin/tenants?q=` → items with `{"id","name","type","plan","devices","users","created_at","suspended"}`
- `PATCH /api/admin/tenants/{id}` `{plan_code?, plan_expires_at?, suspended?, type?}`
- `GET /api/admin/plans`, `PATCH /api/admin/plans/{code}` (prices, limits, features)
