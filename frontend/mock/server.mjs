/**
 * DEV-ONLY mock of the Syriana Energy API (docs/API_CONTRACT.md).
 *   npm run mock            -> listens on :8000 (what BACKEND_URL defaults to)
 * It is not imported by the app and is excluded from the Docker image's runtime.
 *
 * Logins (any non-empty password):
 *   demo@demo.test       pro plan, owner, 1 demo device
 *   free@demo.test       free plan (feature_not_in_plan upsells)
 *   empty@demo.test      pro plan, no devices (empty state)
 *   installer@demo.test  installer plan, 3 tenants, customers + white label
 *   admin@demo.test      superadmin
 *   2fa@demo.test        requires totp_code 123456
 *   noai@demo.test       assistant returns 503 ai_unavailable
 *   offline@demo.test    device is offline
 */
import http from "node:http";

const PORT = Number(process.env.MOCK_PORT || 8000);
const FEATS_ALL = ["control", "ai", "email", "webhook", "automations", "api", "white_label", "customers"];
const PLANS = [
  { code: "free", name: "Free", name_ar: "مجاني", price_month: 0, price_year: 0, currency: "USD", max_devices: 1, history_days: 7, features: [] },
  { code: "home", name: "Home", name_ar: "بيت", price_month: 4, price_year: 40, currency: "USD", max_devices: 3, history_days: 365, features: ["control", "ai", "email"] },
  { code: "pro", name: "Pro", name_ar: "احترافي", price_month: 9, price_year: 90, currency: "USD", max_devices: 10, history_days: 730, features: ["control", "ai", "email", "webhook", "automations", "api"] },
  { code: "installer", name: "Installer", name_ar: "مُركِّب", price_month: 29, price_year: 290, currency: "USD", max_devices: 200, history_days: 1095, features: FEATS_ALL },
];
const planOf = (c) => PLANS.find((p) => p.code === c);
const DEFAULT_BRANDING = { name: "Syriana Energy", name_ar: "سيريانا إنرجي", logo_url: null, primary_color: "#DA7756", accent_color: "#d9b86b", support_email: "support@syriana.software", powered_by: true };

const uid = () => Math.random().toString(36).slice(2, 10);
const iso = (d = new Date()) => new Date(d).toISOString();

/* ---- per-account state, created lazily ---- */
const accounts = new Map();
function account(email) {
  if (accounts.has(email)) return accounts.get(email);
  const kind = email.split("@")[0];
  const planCode = kind === "free" ? "free" : kind === "installer" ? "installer" : kind === "admin" ? "installer" : kind === "demo" || kind === "empty" || kind === "noai" || kind === "2fa" || kind === "offline" ? "pro" : "pro";
  const tenantId = "t_" + uid();
  const siteId = "s_" + uid();
  const a = {
    email, kind, totp: kind === "2fa",
    user: { id: "u_" + uid(), email, name: kind === "admin" ? "Platform Admin" : "محمد", locale: "ar", is_superadmin: kind === "admin", totp_enabled: kind === "2fa" },
    tenantId,
    tenants: {
      [tenantId]: { id: tenantId, name: kind === "installer" ? "Syria Solar Installers" : "بيت محمد", type: kind === "installer" ? "installer" : "home", parent_id: null, planCode, plan_expires_at: iso(Date.now() + 200 * 864e5), branding: { ...DEFAULT_BRANDING }, custom_domain: null, timezone: "Asia/Damascus", created_at: iso(Date.now() - 90 * 864e5) },
    },
    sites: kind === "empty" ? [] : [{ id: siteId, name: "البيت", timezone: "Asia/Damascus" }],
    devices: kind === "empty" ? [] : [{ id: "d_" + uid(), site_id: siteId, name: "إنفرتر البيت", kind: "inverter", driver: "demo", model: "Hybrid 24V 3KW", serial: "96322507123757", created_at: iso(Date.now() - 30 * 864e5), battery_capacity_wh: 4800 }],
    settings: [
      { key: "output_priority", label: "Output priority", label_ar: "أولوية تشغيل البيت", type: "enum", group: "Priority", options: [{ value: "USB", label: "Utility first", label_ar: "الدولة أولاً" }, { value: "SUB", label: "Solar first", label_ar: "الشمس أولاً" }, { value: "SBU", label: "Solar, battery, utility", label_ar: "الشمس ثم البطارية" }], value: "USB" },
      { key: "charger_priority", label: "Charger source", label_ar: "مصدر شحن البطارية", type: "enum", group: "Priority", options: [{ value: "SOLAR_FIRST", label: "Solar first", label_ar: "الشمس أولاً" }, { value: "SOLAR_UTILITY", label: "Solar + utility", label_ar: "شمس + دولة" }, { value: "SOLAR_ONLY", label: "Solar only", label_ar: "الشمس فقط" }], value: "SOLAR_UTILITY" },
      { key: "max_grid_charge_current", label: "Max grid charge current", label_ar: "أقصى تيار شحن من الدولة", type: "number", group: "Charging", min: 10, max: 60, step: 10, unit: "A", value: 30 },
      { key: "max_charge_current", label: "Max total charge current", label_ar: "أقصى تيار شحن كلي", type: "number", group: "Charging", min: 10, max: 80, step: 10, unit: "A", value: 60 },
      { key: "cutoff_voltage", label: "Battery cut-off voltage", label_ar: "جهد فصل البطارية", type: "number", group: "Battery", min: 20, max: 24, step: 0.5, unit: "V", value: 21 },
      { key: "buzzer", label: "Inverter buzzer", label_ar: "صافرة الإنفرتر", type: "bool", group: "General", value: true },
    ],
    commands: [{ id: "c_1", key: "charger_priority", old_value: "SOLAR_FIRST", new_value: "SOLAR_UTILITY", status: "ok", error: null, user_name: "محمد", created_at: iso(Date.now() - 2 * 864e5) }],
    rules: [
      { type: "battery_low", enabled: true, params: { threshold_soc: 30 }, channels: ["telegram", "inapp"], cooldown_minutes: 60 },
      { type: "battery_full", enabled: false, params: { threshold_soc: 100 }, channels: ["inapp"], cooldown_minutes: 120 },
      { type: "grid_lost", enabled: true, params: {}, channels: ["telegram", "inapp"], cooldown_minutes: 5 },
      { type: "grid_restored", enabled: true, params: {}, channels: ["telegram", "inapp"], cooldown_minutes: 5 },
      { type: "overload", enabled: true, params: { threshold_percent: 90, minutes: 3 }, channels: ["telegram", "email", "inapp"], cooldown_minutes: 30 },
      { type: "fault", enabled: true, params: {}, channels: ["telegram", "email", "inapp"], cooldown_minutes: 15 },
      { type: "device_offline", enabled: true, params: { minutes: 10 }, channels: ["telegram", "inapp"], cooldown_minutes: 30 },
      { type: "high_temperature", enabled: true, params: { threshold_c: 60 }, channels: ["inapp"], cooldown_minutes: 30 },
      { type: "daily_summary", enabled: false, params: { hour_local: 21 }, channels: ["telegram"], cooldown_minutes: 1440 },
    ].map((r) => ({ id: "r_" + uid(), ...r })),
    alerts: [
      { type: "grid_lost", severity: "critical", title: "Grid power lost", title_ar: "انقطعت كهرباء الدولة", body: "07:12 · switched to battery automatically", body_ar: "البيت انتقل إلى البطارية تلقائياً", ago: 130 },
      { type: "overload", severity: "warning", title: "High load 2.1 kW for 6 min", title_ar: "حمل مرتفع 2.1 كيلوواط لمدة 6 دقائق", body: "Probably heater and washing machine together", body_ar: "غالباً السخان والغسالة معاً", ago: 900 },
      { type: "battery_full", severity: "info", title: "Battery full 100%", title_ar: "البطارية امتلأت 100%", body: "", body_ar: "", ago: 1300 },
      { type: "grid_restored", severity: "info", title: "Grid power restored", title_ar: "عادت كهرباء الدولة", body: "", body_ar: "", ago: 2900 },
      { type: "device_offline", severity: "warning", title: "Device offline for 12 min", title_ar: "الجهاز غير متصل منذ 12 دقيقة", body: "", body_ar: "", ago: 4000 },
    ].map((x, i) => ({ id: "a_" + i + uid(), device_id: null, device_name: "إنفرتر البيت", created_at: iso(Date.now() - x.ago * 60000), read: i > 2, ...x, ago: undefined })),
    channels: { telegram: { linked: false, chat_title: null }, email: { enabled: true, address: email }, webhook: { enabled: false, url: null } },
    automations: [],
    keys: [],
    users: [{ id: "u_x", email, name: "محمد", role: "owner" }, { id: "u_y", email: "sara@example.com", name: "Sara", role: "viewer" }],
    customers: [
      { id: "c1", name: "بيت أبو أحمد", devices: 1, online: 1, plan: "home", created_at: iso(Date.now() - 40 * 864e5) },
      { id: "c2", name: "محل الأمل", devices: 2, online: 1, plan: "pro", created_at: iso(Date.now() - 10 * 864e5) },
      { id: "c3", name: "Villa Dimashq", devices: 1, online: 0, plan: "free", created_at: iso(Date.now() - 3 * 864e5) },
    ],
  };
  a.devices.forEach((d) => { d.battery_capacity_wh = d.battery_capacity_wh ?? null; });
  if (kind === "installer") {
    a.tenants["t_c1"] = { ...a.tenants[tenantId], id: "t_c1", name: "بيت أبو أحمد", type: "home", parent_id: tenantId, planCode: "home" };
    a.tenants["t_c2"] = { ...a.tenants[tenantId], id: "t_c2", name: "محل الأمل", type: "home", parent_id: tenantId, planCode: "pro" };
  }
  accounts.set(email, a);
  return a;
}

/* ---- synthetic telemetry ---- */
const hourOf = (t) => { const d = new Date(t); return d.getHours() + d.getMinutes() / 60; };
const pvAt = (t) => { const h = hourOf(t); if (h < 6.2 || h > 17.8) return 0; const s = Math.sin(((h - 6.2) / 11.6) * Math.PI); return Math.max(0, 3100 * s * s * (0.88 + 0.12 * Math.sin(t / 240000))); };
const loadAt = (t) => { const h = hourOf(t); return Math.round(380 + 220 * Math.sin(h / 24 * Math.PI * 2 - 1) ** 2 + (h > 18 && h < 22 ? 600 : 0) + 60 * Math.sin(t / 90000)); };
const gridUpAt = (t) => { const h = hourOf(t); return !(h >= 7.2 && h < 12.5) && !(h >= 16 && h < 19); };
const socAt = (t) => { const h = hourOf(t); return Math.round(Math.max(18, Math.min(100, h < 6 ? 62 - h * 4 : h < 15 ? 38 + (h - 6) * 7 : 100 - (h - 15) * 7.5))); };
function metricsAt(t, offline) {
  const pv = pvAt(t), load = loadAt(t), up = gridUpAt(t);
  const bp = pv - load;
  return {
    grid_voltage: up ? 229.4 : 0, grid_frequency: up ? 50 : 0, grid_power: up ? Math.max(0, load - pv) : 0, grid_available: up,
    pv_voltage: pv > 5 ? 228.7 : 0, pv_current: pv > 5 ? Math.round(pv / 228.7 * 10) / 10 : 0, pv_power: Math.round(pv),
    battery_voltage: 26.9, battery_soc: socAt(t), battery_power: Math.round(bp),
    battery_charge_current: bp > 0 ? Math.round(bp / 26.9) : 0, battery_discharge_current: bp < 0 ? Math.round(-bp / 26.9) : 0,
    load_power: load, load_apparent_power: Math.round(load * 1.08), load_percent: Math.round(load / 3000 * 100), output_voltage: 230, output_frequency: 50,
    bus_voltage: 379, inverter_temperature: 41, mode: up ? "line" : "battery", output_priority: "USB", charger_priority: "SUB",
    energy_pv_today: 4.2, energy_pv_total: 2584.3, energy_load_today: 3.1, fault_codes: [],
  };
}
function seriesFor(metric, from, to, step) {
  const out = [];
  for (let t = Math.ceil(from / step) * step; t <= Math.min(to, Date.now()); t += step) {
    const m = metricsAt(t);
    out.push([iso(t), m[metric] ?? null]);
  }
  return out;
}
const BUCKET = { raw: 30e3, "1m": 60e3, "5m": 300e3, "15m": 900e3, "1h": 3600e3, "1d": 86400e3 };

/* ---- http helpers ---- */
const send = (res, status, body, headers = {}) => {
  const data = body === undefined ? "" : JSON.stringify(body);
  res.writeHead(status, { "content-type": "application/json", ...headers });
  res.end(data);
};
const err = (res, status, code, message, message_ar) => send(res, status, { error: { code, message, message_ar: message_ar || message } });
const readBody = (req) => new Promise((r) => { let s = ""; req.on("data", (c) => (s += c)); req.on("end", () => { try { r(s ? JSON.parse(s) : {}); } catch { r({}); } }); });
const cookieOf = (req) => (req.headers.cookie || "").split(/;\s*/).map((c) => c.split("=")).find(([k]) => k === "se_session")?.[1];

function view(a) {
  const t = a.tenants[a.tenantId];
  const { planCode, ...rest } = t;
  return { user: a.user, tenant: { ...rest, plan: planOf(planCode) }, role: "owner", tenants: Object.values(a.tenants).filter((x) => a.kind === "installer" ? true : x.id === a.tenantId).map((x) => ({ id: x.id, name: x.name, role: "owner" })) };
}
const devView = (a, d) => { const off = a.kind === "offline"; return { ...d, online: !off, last_seen: off ? iso(Date.now() - 3 * 3600e3) : iso(), last_metrics: off ? null : metricsAt(Date.now()) }; };
const need = (a, f) => planOf(a.tenants[a.tenantId].planCode).features.includes(f);

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://x");
  const path = url.pathname.replace(/^\/api/, "");
  const q = url.searchParams;
  const method = req.method;
  const body = ["POST", "PATCH", "PUT", "DELETE"].includes(method) ? await readBody(req) : {};
  await new Promise((r) => setTimeout(r, 60));

  try {
    if (path === "/health") return send(res, 200, { ok: true, version: "mock" });
    if (path === "/public/branding") {
      const host = q.get("host") || "";
      if (host.startsWith("brand.")) return send(res, 200, { name: "Shams Energy", name_ar: "طاقة الشمس", logo_url: null, primary_color: "#2f9e8f", accent_color: "#e0b341", support_email: "hi@shams.test", powered_by: false });
      return send(res, 200, DEFAULT_BRANDING);
    }
    if (path === "/public/plans") return send(res, 200, PLANS);

    if (path === "/auth/register" && method === "POST") {
      if (!body.email || !body.password) return err(res, 422, "validation_error", "Missing fields", "حقول ناقصة");
      const a = account(body.email.toLowerCase());
      a.user.name = body.name || a.user.name; a.user.locale = body.locale || "ar";
      return send(res, 201, view(a), { "set-cookie": `se_session=${encodeURIComponent(a.email)}; Path=/; HttpOnly; SameSite=Lax` });
    }
    if (path === "/auth/login" && method === "POST") {
      if (!body.email || !body.password) return err(res, 401, "invalid_credentials", "Invalid email or password", "البريد أو كلمة المرور غير صحيحة");
      const a = account(String(body.email).toLowerCase());
      if (a.totp && body.totp_code !== "123456") {
        return body.totp_code ? err(res, 401, "invalid_totp", "Invalid code", "الرمز غير صحيح") : err(res, 401, "totp_required", "2FA code required", "مطلوب رمز التحقق");
      }
      return send(res, 200, view(a), { "set-cookie": `se_session=${encodeURIComponent(a.email)}; Path=/; HttpOnly; SameSite=Lax` });
    }
    if (path === "/auth/logout") return send(res, 204, undefined, { "set-cookie": "se_session=; Path=/; Max-Age=0; HttpOnly" });

    const email = cookieOf(req);
    if (!email) return err(res, 401, "unauthorized", "Not signed in", "غير مسجّل الدخول");
    const a = account(decodeURIComponent(email));
    const tn = a.tenants[a.tenantId];
    const gate = (f) => { if (!need(a, f)) { err(res, 403, "feature_not_in_plan", `Your plan does not include ${f}`, "باقتك لا تشمل هذه الميزة"); return true; } return false; };

    if (path === "/auth/me") {
      if (method === "PATCH") { Object.assign(a.user, { name: body.name ?? a.user.name, locale: body.locale ?? a.user.locale }); }
      return send(res, 200, view(a));
    }
    if (path === "/auth/switch-tenant") { if (!a.tenants[body.tenant_id]) return err(res, 404, "not_found", "Not found"); a.tenantId = body.tenant_id; return send(res, 200, view(a)); }
    if (path === "/auth/totp/setup") return send(res, 200, { secret: "JBSWY3DPEHPK3PXP", otpauth_url: "otpauth://totp/Syriana%20Energy:" + encodeURIComponent(a.email) + "?secret=JBSWY3DPEHPK3PXP&issuer=Syriana%20Energy" });
    if (path === "/auth/totp/enable") { if (body.code !== "123456") return err(res, 400, "invalid_totp", "Invalid code", "الرمز غير صحيح"); a.user.totp_enabled = true; return send(res, 200, { ok: true }); }
    if (path === "/auth/totp/disable") { if (body.code !== "123456") return err(res, 400, "invalid_totp", "Invalid code", "الرمز غير صحيح"); a.user.totp_enabled = false; return send(res, 200, { ok: true }); }

    if (path === "/tenant") { if (method === "PATCH") Object.assign(tn, body); return send(res, 200, view(a).tenant); }
    if (path === "/tenant/branding") { if (gate("white_label")) return; Object.assign(tn.branding, body, { powered_by: false }); if ("custom_domain" in body) tn.custom_domain = body.custom_domain; return send(res, 200, view(a).tenant); }
    if (path === "/tenant/usage") return send(res, 200, { devices: a.devices.length, max_devices: planOf(tn.planCode).max_devices, history_days: planOf(tn.planCode).history_days });

    if (path === "/customers") {
      if (gate("customers")) return;
      if (method === "POST") { const c = { id: "c_" + uid(), name: body.name, devices: 0, online: 0, plan: "free", created_at: iso() }; a.customers.push(c); a.tenants["t_" + c.id] = { ...tn, id: "t_" + c.id, name: c.name, type: "home", parent_id: tn.id, planCode: "free" }; return send(res, 201, c); }
      return send(res, 200, { items: a.customers, total: a.customers.length });
    }
    let m;
    if ((m = path.match(/^\/customers\/(.+)$/)) && method === "DELETE") { a.customers = a.customers.filter((c) => c.id !== m[1]); return send(res, 204); }

    if (path === "/users") {
      if (method === "POST") { const u = { id: "u_" + uid(), email: body.email, name: body.name, role: body.role }; a.users.push(u); return send(res, 201, u); }
      return send(res, 200, { items: a.users, total: a.users.length });
    }
    if ((m = path.match(/^\/users\/(.+)$/))) {
      if (method === "DELETE") { a.users = a.users.filter((u) => u.id !== m[1]); return send(res, 204); }
      const u = a.users.find((x) => x.id === m[1]); if (u) Object.assign(u, body); return send(res, 200, u);
    }

    if (path === "/sites") {
      if (method === "POST") { const s = { id: "s_" + uid(), name: body.name, timezone: "Asia/Damascus" }; a.sites.push(s); return send(res, 201, { ...s, devices: [] }); }
      return send(res, 200, a.sites.map((s) => ({ ...s, devices: a.devices.filter((d) => d.site_id === s.id).map((d) => devView(a, d)) })));
    }
    if ((m = path.match(/^\/sites\/(.+)$/))) {
      if (method === "DELETE") { a.sites = a.sites.filter((s) => s.id !== m[1]); a.devices = a.devices.filter((d) => d.site_id !== m[1]); return send(res, 204); }
      const s = a.sites.find((x) => x.id === m[1]); if (s) Object.assign(s, { name: body.name ?? s.name }); return send(res, 200, { ...s, devices: [] });
    }
    if (path === "/drivers") return send(res, 200, [
      { code: "eybond_cloud", name: "WatchPower / SmartESS / ShineMonitor", name_ar: "واتش باور / سمارت إي إس إس / شاين مونيتور", kind: "inverter", credential_fields: [{ key: "username", label: "Username", label_ar: "اسم المستخدم", type: "text", required: true }, { key: "password", label: "Password", label_ar: "كلمة المرور", type: "password", required: true }], supports_control: true, supports_discovery: true },
      { code: "demo", name: "Demo (simulated 24V hybrid inverter)", name_ar: "تجريبي (إنفرتر هايبرد 24V محاكى)", kind: "inverter", credential_fields: [], supports_control: true, supports_discovery: true },
    ]);
    if (path === "/integrations/discover") {
      if (body.driver === "eybond_cloud" && body.credentials?.password === "bad") return err(res, 400, "invalid_credentials", "Vendor rejected the credentials", "رفضت الشركة المصنّعة بيانات الدخول");
      return send(res, 200, { integration_token: "tok_" + uid(), devices: [{ external_id: "SN96322507123757", name: "Hybrid 24V 3KW", model: "Hybrid 24V 3KW", serial: "96322507123757", meta: {} }, { external_id: "SN11223344", name: "Hybrid 48V 5KW", model: "Hybrid 48V 5KW", serial: "11223344", meta: {} }] });
    }
    if (path === "/devices" && method === "POST") {
      if (a.devices.length >= planOf(tn.planCode).max_devices) return err(res, 403, "plan_limit", "Device limit reached for your plan", "وصلت للحد الأقصى للأجهزة في باقتك");
      const d = { id: "d_" + uid(), site_id: body.site_id, name: body.name, kind: "inverter", driver: body.driver, model: body.driver === "demo" ? "Demo 24V" : "Hybrid", serial: body.external_id, created_at: iso(), battery_capacity_wh: null };
      a.devices.push(d); return send(res, 201, devView(a, d));
    }
    if ((m = path.match(/^\/devices\/([^/]+)(?:\/(\w+))?$/))) {
      const d = a.devices.find((x) => x.id === m[1]);
      if (!d) return err(res, 404, "not_found", "Device not found", "الجهاز غير موجود");
      const sub = m[2];
      if (!sub) {
        if (method === "DELETE") { a.devices = a.devices.filter((x) => x !== d); return send(res, 204); }
        if (method === "PATCH") Object.assign(d, body);
        return send(res, 200, devView(a, d));
      }
      if (sub === "live") { const off = a.kind === "offline"; return send(res, 200, { device_id: d.id, ts: off ? iso(Date.now() - 3 * 3600e3) : iso(Date.now() - Math.floor(Math.random() * 8000)), online: !off, metrics: off ? {} : metricsAt(Date.now()), raw: {} }); }
      if (sub === "history") {
        const to = q.get("to") ? Date.parse(q.get("to")) : Date.now(); const from = q.get("from") ? Date.parse(q.get("from")) : to - 864e5;
        const step = BUCKET[q.get("bucket") || "5m"] || 300e3;
        const series = {}; for (const k of (q.get("metrics") || "pv_power").split(",")) series[k] = seriesFor(k, from, to, step);
        return send(res, 200, { bucket: q.get("bucket") || "5m", series });
      }
      if (sub === "energy") {
        const days = Number(q.get("days") || 30); const out = [];
        for (let i = days - 1; i >= 0; i--) { const dt = new Date(Date.now() - i * 864e5); const k = (dt.getDate() * 7 + i * 3) % 10; const pv = i === 0 ? 4.2 : 6 + (k % 6) * 0.9; out.push({ date: dt.toISOString().slice(0, 10), pv_kwh: Math.round(pv * 10) / 10, load_kwh: Math.round((4.5 + (k % 4) * 0.7) * 10) / 10, grid_kwh: Math.round((2.2 + (k % 5) * 0.5) * 10) / 10 }); }
        return send(res, 200, out);
      }
      if (sub === "today") {
        const d0 = new Date(); d0.setHours(7, 12, 0, 0); const d1 = new Date(); d1.setHours(12, 30, 0, 0);
        const outages = []; if (Date.now() > d0.getTime()) outages.push({ from: iso(d0), to: Date.now() > d1.getTime() ? iso(d1) : null });
        return send(res, 200, { pv_kwh: 4.2, load_kwh: 3.1, grid_kwh: 0.6, grid_outages: outages, battery_runtime_hours: 5.67 });
      }
      if (sub === "settings") {
        if (gate("control")) return;
        if (method === "POST") {
          if (body.confirm !== true) return err(res, 400, "confirm_required", "Confirmation required", "التأكيد مطلوب");
          const s = a.settings.find((x) => x.key === body.key); if (!s) return err(res, 404, "not_found", "Unknown setting");
          if (s.type === "number" && (body.value < s.min || body.value > s.max)) return err(res, 422, "unsafe_value", `Value must be between ${s.min} and ${s.max}`, `القيمة يجب أن تكون بين ${s.min} و ${s.max}`);
          const failed = body.key === "buzzer" && body.value === false && a.kind === "free";
          const c = { id: "c_" + uid(), key: s.key, old_value: s.value, new_value: body.value, status: failed ? "failed" : "ok", error: failed ? "Inverter rejected" : null, user_name: a.user.name, created_at: iso() };
          if (!failed) s.value = body.value; a.commands.unshift(c); return send(res, 200, c);
        }
        return send(res, 200, a.settings);
      }
      if (sub === "commands") { if (gate("control")) return; return send(res, 200, { items: a.commands, total: a.commands.length }); }
    }

    if (path === "/alert-rules") {
      if (method === "POST") { const r = { id: "r_" + uid(), ...body }; a.rules.push(r); return send(res, 201, r); }
      return send(res, 200, { items: a.rules, total: a.rules.length });
    }
    if ((m = path.match(/^\/alert-rules\/(.+)$/))) {
      if (method === "DELETE") { a.rules = a.rules.filter((r) => r.id !== m[1]); return send(res, 204); }
      const r = a.rules.find((x) => x.id === m[1]); if (r) Object.assign(r, body); return send(res, 200, r);
    }
    if (path === "/alerts") { const l = Number(q.get("limit") || 50); return send(res, 200, { items: a.alerts.slice(0, l), total: a.alerts.length }); }
    if (path === "/alerts/read-all") { a.alerts.forEach((x) => (x.read = true)); return send(res, 200, { ok: true }); }
    if ((m = path.match(/^\/alerts\/(.+)\/read$/))) { const x = a.alerts.find((y) => y.id === m[1]); if (x) x.read = true; return send(res, 200, { ok: true }); }

    if (path === "/channels") {
      if (method === "PATCH") { if (body.email) Object.assign(a.channels.email, body.email); if (body.webhook) { if (gate("webhook")) return; Object.assign(a.channels.webhook, body.webhook); } }
      return send(res, 200, a.channels);
    }
    if (path === "/channels/telegram/link") return send(res, 200, { code: "ABC123", bot_username: "SyrianaEnergyBot", deep_link: "https://t.me/SyrianaEnergyBot?start=ABC123" });
    if (path === "/channels/test") return send(res, 200, { ok: true });

    if (path === "/automations") {
      if (gate("automations")) return;
      if (method === "POST") { const x = { id: "au_" + uid(), state: "idle", last_triggered_at: null, ...body }; a.automations.push(x); return send(res, 201, x); }
      return send(res, 200, { items: a.automations, total: a.automations.length });
    }
    if ((m = path.match(/^\/automations\/(.+)$/))) {
      if (method === "DELETE") { a.automations = a.automations.filter((r) => r.id !== m[1]); return send(res, 204); }
      const r = a.automations.find((x) => x.id === m[1]); if (r) Object.assign(r, body); return send(res, 200, r);
    }

    if (path === "/assistant/chat") {
      if (gate("ai")) return;
      if (a.kind === "noai") return err(res, 503, "ai_unavailable", "The assistant is not configured", "المساعد غير مُفعّل حالياً");
      const last = body.messages?.[body.messages.length - 1]?.content || "";
      return send(res, 200, { reply: `(mock) سؤالك: «${last}»\n\nالحمل الليلة حوالي 450 واط والبطارية 70%، فتكفيك تقريباً 5 ساعات ونصف.`, used_tools: ["get_live_status", "get_today_summary"] });
    }

    if (path === "/api-keys") {
      if (gate("api")) return;
      if (method === "POST") { const k = { id: "k_" + uid(), name: body.name, key: "se_live_" + uid() + uid() + uid(), created_at: iso() }; a.keys.push({ ...k, key: undefined }); return send(res, 201, k); }
      return send(res, 200, { items: a.keys, total: a.keys.length });
    }
    if ((m = path.match(/^\/api-keys\/(.+)$/))) { a.keys = a.keys.filter((k) => k.id !== m[1]); return send(res, 204); }

    if (path.startsWith("/admin")) {
      if (!a.user.is_superadmin) return err(res, 403, "forbidden", "Superadmin only", "للمشرف العام فقط");
      if (path === "/admin/stats") { const s = []; for (let i = 29; i >= 0; i--) s.push([new Date(Date.now() - i * 864e5).toISOString().slice(0, 10), (i * 7) % 5 + (i % 3)]); return send(res, 200, { tenants: 128, users: 171, devices: 203, devices_online: 188, by_plan: { free: 70, home: 38, pro: 14, installer: 6 }, signups_30d: s, mrr_estimate: 612 }); }
      if (path === "/admin/tenants") {
        if (method === "PATCH") return send(res, 200, {});
        const list = [{ id: "t1", name: "بيت محمد", type: "home", plan: "pro", devices: 1, users: 1, created_at: iso(Date.now() - 90 * 864e5), suspended: false, plan_expires_at: iso(Date.now() + 200 * 864e5) }, { id: "t2", name: "Syria Solar Installers", type: "installer", plan: "installer", devices: 42, users: 5, created_at: iso(Date.now() - 60 * 864e5), suspended: false, plan_expires_at: iso(Date.now() + 20 * 864e5) }, { id: "t3", name: "Demo Free", type: "home", plan: "free", devices: 1, users: 1, created_at: iso(Date.now() - 5 * 864e5), suspended: true, plan_expires_at: null }];
        const qq = (q.get("q") || "").toLowerCase();
        const items = list.filter((t) => t.name.toLowerCase().includes(qq)); return send(res, 200, { items, total: items.length });
      }
      if ((m = path.match(/^\/admin\/tenants\/(.+)$/))) return send(res, 200, { id: m[1], name: "x", type: "home", plan: body.plan_code || "free", devices: 0, users: 1, created_at: iso(), suspended: !!body.suspended });
      if (path === "/admin/plans") return send(res, 200, PLANS);
      if ((m = path.match(/^\/admin\/plans\/(.+)$/))) { const p = planOf(m[1]); if (p) Object.assign(p, body); return send(res, 200, p); }
    }
    return err(res, 404, "not_found", `No route ${method} ${path}`, "غير موجود");
  } catch (e) {
    console.error(e);
    return err(res, 500, "internal", String(e?.message || e));
  }
});
server.listen(PORT, () => console.log(`mock api on :${PORT}`));
