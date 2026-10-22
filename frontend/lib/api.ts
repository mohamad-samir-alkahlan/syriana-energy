/* Typed client mirroring docs/API_CONTRACT.md (v1). */

export type Locale = "ar" | "en";

export interface Metrics {
  grid_voltage?: number | null;
  grid_frequency?: number | null;
  grid_power?: number | null;
  grid_available?: boolean | null;
  pv_voltage?: number | null;
  pv_current?: number | null;
  pv_power?: number | null;
  battery_voltage?: number | null;
  battery_soc?: number | null;
  battery_power?: number | null;
  battery_charge_current?: number | null;
  battery_discharge_current?: number | null;
  load_power?: number | null;
  load_apparent_power?: number | null;
  load_percent?: number | null;
  output_voltage?: number | null;
  output_frequency?: number | null;
  bus_voltage?: number | null;
  inverter_temperature?: number | null;
  mode?: "line" | "battery" | "standby" | "fault" | "bypass" | "off" | "unknown" | null;
  output_priority?: string | null;
  charger_priority?: string | null;
  energy_pv_today?: number | null;
  energy_pv_total?: number | null;
  energy_load_today?: number | null;
  fault_codes?: string[] | null;
}
export type MetricKey = keyof Metrics;

export interface LiveStatus {
  device_id: string;
  ts: string;
  online: boolean;
  metrics: Metrics;
  raw: Record<string, unknown>;
}

export interface Branding {
  name: string;
  name_ar: string;
  logo_url: string | null;
  primary_color: string;
  accent_color: string;
  support_email: string | null;
  powered_by: boolean;
}

export type PlanCode = "free" | "home" | "pro" | "installer";
export type Feature =
  | "control"
  | "ai"
  | "email"
  | "webhook"
  | "automations"
  | "api"
  | "white_label"
  | "customers";

export interface Plan {
  code: PlanCode;
  name: string;
  name_ar: string;
  price_month: number;
  price_year: number;
  currency: string;
  max_devices: number;
  history_days: number;
  features: Feature[];
}

export interface Tenant {
  id: string;
  name: string;
  type: "home" | "installer";
  parent_id: string | null;
  plan: Plan;
  plan_expires_at: string | null;
  branding: Branding;
  custom_domain: string | null;
  timezone: string;
  created_at: string;
}

export interface Me {
  user: {
    id: string;
    email: string;
    name: string;
    locale: Locale;
    is_superadmin: boolean;
    totp_enabled: boolean;
    email_verified?: boolean;
  };
  tenant: Tenant;
  role: "owner" | "admin" | "viewer";
  tenants: { id: string; name: string; role: string }[];
}

export interface Device {
  id: string;
  site_id: string;
  name: string;
  kind: "inverter" | "battery" | "network";
  driver: string;
  model: string | null;
  serial: string | null;
  online: boolean;
  last_seen: string | null;
  last_metrics: Metrics | null;
  created_at: string;
  battery_capacity_wh?: number | null;
}
export interface Site {
  id: string;
  name: string;
  timezone: string;
  devices: Device[];
}

export interface DriverInfo {
  code: string;
  name: string;
  name_ar: string;
  kind: Device["kind"];
  credential_fields: { key: string; label: string; label_ar: string; type: "text" | "password"; required: boolean }[];
  supports_control: boolean;
  supports_discovery: boolean;
}
export interface DiscoveredDevice {
  external_id: string;
  name: string;
  model: string | null;
  serial: string | null;
  meta: Record<string, unknown>;
}

export interface HistoryResponse {
  bucket: string;
  series: Record<string, [string, number | null][]>;
}
export interface EnergyDay {
  date: string;
  pv_kwh: number | null;
  load_kwh: number | null;
  grid_kwh: number | null;
}
export interface TodaySummary {
  pv_kwh: number | null;
  load_kwh: number | null;
  grid_kwh: number | null;
  grid_outages: { from: string; to: string | null }[];
  battery_runtime_hours: number | null;
}

export interface Setting {
  key: string;
  label: string;
  label_ar: string;
  type: "enum" | "number" | "bool";
  options?: { value: string; label: string; label_ar: string }[];
  min?: number | null;
  max?: number | null;
  step?: number | null;
  unit?: string | null;
  value: string | number | boolean | null;
  group?: string | null;
  help?: string | null;
  help_ar?: string | null;
  caution?: string | null;
  caution_ar?: string | null;
}
export interface Command {
  id: string;
  key: string;
  old_value: unknown;
  new_value: unknown;
  status: "pending" | "ok" | "failed";
  error: string | null;
  user_name: string | null;
  created_at: string;
}

export type AlertType =
  | "battery_low"
  | "battery_full"
  | "grid_lost"
  | "grid_restored"
  | "overload"
  | "fault"
  | "device_offline"
  | "high_temperature"
  | "daily_summary";
export type Channel = "telegram" | "email" | "webhook" | "inapp";
export interface AlertRule {
  id: string;
  type: AlertType;
  enabled: boolean;
  params: Record<string, number>;
  channels: Channel[];
  cooldown_minutes: number;
}
export interface Alert {
  id: string;
  device_id: string | null;
  device_name: string | null;
  type: AlertType | string;
  severity: "info" | "warning" | "critical";
  title: string;
  title_ar: string;
  body: string;
  body_ar: string;
  created_at: string;
  read: boolean;
}
export interface Page<T> {
  items: T[];
  total: number;
}

export interface ChannelsState {
  telegram: { linked: boolean; chat_title: string | null; chats?: { id: string; title: string | null; linked_at: string | null }[] };
  email: { enabled: boolean; address: string | null };
  webhook: { enabled: boolean; url: string | null };
}

export type AutoOp = "<" | ">" | "<=" | ">=" | "==";
export interface AutoCondition {
  metric: string;
  op: AutoOp;
  value: number;
}
export type AutoAction =
  | { type: "notify"; message: string }
  | { type: "http"; method: string; url: string; body?: string }
  | { type: "setting"; key: string; value: string | number | boolean };
export interface Automation {
  id: string;
  name: string;
  enabled: boolean;
  device_id: string | null;
  conditions: AutoCondition[];
  grid: "any" | "available" | "lost";
  actions: AutoAction[];
  recover_conditions: AutoCondition[];
  recover_actions: AutoAction[];
  state: "idle" | "active";
  last_triggered_at: string | null;
}
export type AutomationInput = Omit<Automation, "id" | "state" | "last_triggered_at">;

export interface ApiKey {
  id: string;
  name: string;
  key?: string;
  created_at?: string;
  last_used_at?: string | null;
}
export interface TeamUser {
  id: string;
  email: string;
  name: string;
  role: "owner" | "admin" | "viewer";
}
export interface Customer {
  id: string;
  name: string;
  devices: number;
  online: number;
  plan: string;
  created_at: string;
}
export interface Usage {
  devices: number;
  max_devices: number;
  history_days: number;
}
export interface AdminStats {
  tenants: number;
  users: number;
  devices: number;
  devices_online: number;
  by_plan: Record<string, number>;
  signups_30d: [string, number][];
  mrr_estimate: number;
}
export interface AdminTenant {
  id: string;
  name: string;
  type: string;
  plan: string;
  devices: number;
  users: number;
  created_at: string;
  suspended: boolean;
  plan_expires_at?: string | null;
}
export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

/* ---------- transport ---------- */

export class ApiError extends Error {
  status: number;
  code: string;
  messageAr: string;
  constructor(status: number, code: string, message: string, messageAr?: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.messageAr = messageAr || message;
  }
  text(locale: Locale | string) {
    return locale === "ar" ? this.messageAr || this.message : this.message;
  }
}

type Opts = {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  headers?: Record<string, string>;
};

export function qs(query?: Opts["query"]) {
  if (!query) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export async function request<T>(path: string, opts: Opts = {}): Promise<T> {
  const url = `/api${path}${qs(opts.query)}`;
  const hasBody = opts.body !== undefined;
  let res: Response;
  try {
    res = await fetch(url, {
      method: opts.method || (hasBody ? "POST" : "GET"),
      credentials: "include",
      headers: { ...(hasBody ? { "Content-Type": "application/json" } : {}), ...opts.headers },
      body: hasBody ? JSON.stringify(opts.body) : undefined,
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "network_error", "Network error", "تعذّر الاتصال بالخادم");
  }
  if (res.status === 204) return undefined as T;
  let data: unknown = null;
  const txt = await res.text();
  if (txt) {
    try {
      data = JSON.parse(txt);
    } catch {
      data = null;
    }
  }
  if (!res.ok) {
    const e = (data as { error?: { code?: string; message?: string; message_ar?: string } } | null)?.error;
    throw new ApiError(res.status, e?.code || `http_${res.status}`, e?.message || res.statusText || "Request failed", e?.message_ar);
  }
  return data as T;
}

const j = (body: unknown, method = "POST") => ({ method, body });

export const api = {
  health: () => request<{ ok: boolean; version: string }>("/health"),
  branding: (host: string) => request<Branding>("/public/branding", { query: { host } }),
  plans: () => request<Plan[]>("/public/plans"),

  register: (b: { email: string; password: string; name: string; tenant_name: string; locale: Locale }) =>
    request<Me>("/auth/register", j(b)),
  login: (b: { email: string; password: string; totp_code?: string }) => request<Me>("/auth/login", j(b)),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  me: () => request<Me>("/auth/me"),
  forgotPassword: (email: string, locale: Locale) => request<void>("/auth/password/forgot", j({ email, locale })),
  resetPassword: (token: string, password: string) => request<void>("/auth/password/reset", j({ token, password })),
  verifyEmail: (token: string) => request<void>("/auth/verify-email", j({ token })),
  resendVerification: () => request<void>("/auth/verify-email/send", { method: "POST" }),
  switchTenant: (tenant_id: string) => request<Me>("/auth/switch-tenant", j({ tenant_id })),
  totpSetup: () => request<{ secret: string; otpauth_url: string }>("/auth/totp/setup", { method: "POST" }),
  totpEnable: (code: string) => request<unknown>("/auth/totp/enable", j({ code })),
  totpDisable: (code: string) => request<unknown>("/auth/totp/disable", j({ code })),
  updateMe: (b: { name?: string; locale?: Locale; password?: string; current_password?: string }) =>
    request<Me>("/auth/me", j(b, "PATCH")),

  tenant: () => request<Tenant>("/tenant"),
  updateTenant: (b: { name?: string; timezone?: string }) => request<Tenant>("/tenant", j(b, "PATCH")),
  updateBranding: (b: Partial<Branding> & { custom_domain?: string | null }) =>
    request<Tenant>("/tenant/branding", j(b, "PATCH")),
  usage: () => request<Usage>("/tenant/usage"),

  customers: () => request<Page<Customer>>("/customers"),
  createCustomer: (b: { name: string; owner_email: string; owner_name: string; password?: string }) =>
    request<Customer>("/customers", j(b)),
  deleteCustomer: (id: string) => request<void>(`/customers/${id}`, { method: "DELETE" }),

  users: () => request<TeamUser[] | Page<TeamUser>>("/users"),
  createUser: (b: { email: string; name: string; role: string; password: string }) => request<TeamUser>("/users", j(b)),
  updateUser: (id: string, b: { role: string }) => request<TeamUser>(`/users/${id}`, j(b, "PATCH")),
  deleteUser: (id: string) => request<void>(`/users/${id}`, { method: "DELETE" }),

  sites: () => request<Site[] | Page<Site>>("/sites"),
  createSite: (b: { name: string }) => request<Site>("/sites", j(b)),
  updateSite: (id: string, b: { name?: string }) => request<Site>(`/sites/${id}`, j(b, "PATCH")),
  deleteSite: (id: string) => request<void>(`/sites/${id}`, { method: "DELETE" }),
  drivers: () => request<DriverInfo[]>("/drivers"),
  discover: (b: { driver: string; credentials: Record<string, string> }) =>
    request<{ integration_token: string; devices: DiscoveredDevice[] }>("/integrations/discover", j(b)),
  createDevice: (b: {
    site_id: string;
    driver: string;
    integration_token?: string;
    credentials?: Record<string, string>;
    external_id: string;
    name: string;
  }) => request<Device>("/devices", j(b)),
  device: (id: string) => request<Device>(`/devices/${id}`),
  updateDevice: (id: string, b: { name?: string; battery_capacity_wh?: number | null }) =>
    request<Device>(`/devices/${id}`, j(b, "PATCH")),
  deleteDevice: (id: string) => request<void>(`/devices/${id}`, { method: "DELETE" }),
  live: (id: string) => request<LiveStatus>(`/devices/${id}/live`),
  history: (id: string, q: { from?: string; to?: string; metrics: string; bucket?: string }) =>
    request<HistoryResponse>(`/devices/${id}/history`, { query: q }),
  energy: (id: string, days = 30) => request<EnergyDay[]>(`/devices/${id}/energy`, { query: { days } }),
  today: (id: string) => request<TodaySummary>(`/devices/${id}/today`),

  settings: (id: string) => request<Setting[]>(`/devices/${id}/settings`),
  changeSetting: (id: string, key: string, value: unknown) =>
    request<Command>(`/devices/${id}/settings`, j({ key, value, confirm: true })),
  commands: (id: string) => request<Page<Command> | Command[]>(`/devices/${id}/commands`),

  alertRules: () => request<AlertRule[] | Page<AlertRule>>("/alert-rules"),
  createAlertRule: (b: Omit<AlertRule, "id">) => request<AlertRule>("/alert-rules", j(b)),
  updateAlertRule: (id: string, b: Partial<AlertRule>) => request<AlertRule>(`/alert-rules/${id}`, j(b, "PATCH")),
  deleteAlertRule: (id: string) => request<void>(`/alert-rules/${id}`, { method: "DELETE" }),
  alerts: (q: { limit?: number; offset?: number; device_id?: string } = {}) => request<Page<Alert>>("/alerts", { query: q }),
  readAll: () => request<unknown>("/alerts/read-all", { method: "POST" }),
  readAlert: (id: string) => request<unknown>(`/alerts/${id}/read`, { method: "POST" }),

  channels: () => request<ChannelsState>("/channels"),
  telegramLink: () =>
    request<{ code: string; bot_username: string; deep_link: string }>("/channels/telegram/link", { method: "POST" }),
  updateChannels: (b: { email?: { enabled: boolean; address: string }; webhook?: { enabled: boolean; url: string } }) =>
    request<ChannelsState>("/channels", j(b, "PATCH")),
  telegramUnlink: (chatId: string) =>
    request<ChannelsState>(`/channels/telegram/${encodeURIComponent(chatId)}`, { method: "DELETE" }),
  testChannel: (channel: string) => request<unknown>("/channels/test", j({ channel })),

  automations: () => request<Automation[] | Page<Automation>>("/automations"),
  createAutomation: (b: AutomationInput) => request<Automation>("/automations", j(b)),
  updateAutomation: (id: string, b: Partial<AutomationInput>) => request<Automation>(`/automations/${id}`, j(b, "PATCH")),
  deleteAutomation: (id: string) => request<void>(`/automations/${id}`, { method: "DELETE" }),

  chat: (b: { messages: ChatMessage[]; device_id?: string }) =>
    request<{ reply: string; used_tools: string[] }>("/assistant/chat", j(b)),

  apiKeys: () => request<ApiKey[] | Page<ApiKey>>("/api-keys"),
  createApiKey: (name: string) => request<ApiKey>("/api-keys", j({ name })),
  deleteApiKey: (id: string) => request<void>(`/api-keys/${id}`, { method: "DELETE" }),

  adminStats: () => request<AdminStats>("/admin/stats"),
  adminTenants: (q?: string) => request<Page<AdminTenant> | AdminTenant[]>("/admin/tenants", { query: { q } }),
  adminUpdateTenant: (id: string, b: { plan_code?: string; plan_expires_at?: string | null; suspended?: boolean; type?: string }) =>
    request<AdminTenant>(`/admin/tenants/${id}`, j(b, "PATCH")),
  adminPlans: () => request<Plan[]>("/admin/plans"),
  adminUpdatePlan: (code: string, b: Partial<Plan>) => request<Plan>(`/admin/plans/${code}`, j(b, "PATCH")),
};

/** The contract says list endpoints are paginated `{items,total}`, but some are plain arrays; accept both. */
export function items<T>(x: T[] | Page<T> | undefined | null): T[] {
  if (!x) return [];
  return Array.isArray(x) ? x : x.items ?? [];
}

export const DEFAULT_BRANDING: Branding = {
  name: "Syriana Energy",
  name_ar: "سيريانا إنرجي",
  logo_url: null,
  primary_color: "#DA7756",
  accent_color: "#d9b86b",
  support_email: null,
  powered_by: true,
};
