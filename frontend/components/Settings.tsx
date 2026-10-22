"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import QRCode from "qrcode";
import { usePathname, useRouter } from "@/i18n/navigation";
import { api, ApiError, items, type ApiKey, type Locale, type TeamUser } from "@/lib/api";
import { canWrite, useApi, useMe } from "@/lib/hooks";
import { fmtDate } from "@/lib/format";
import { Icon } from "./Icon";
import { PlanCard } from "./Landing";
import { useBranding, useToast } from "./Providers";
import { Badge, Button, Card, CardTitle, ConfirmModal, ErrorState, Input, Modal, PageHeader, Segmented, Select, Skeleton, Switch, Tabs, Upsell, cx, errorText } from "./ui";

type Tab = "profile" | "security" | "notifications" | "keys" | "team" | "plan";
const TABS: Tab[] = ["profile", "security", "notifications", "keys", "team", "plan"];

export function Settings() {
  const t = useTranslations("settings");
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const raw = sp.get("tab") as Tab | null;
  const tab: Tab = raw && TABS.includes(raw) ? raw : "profile";
  const icons = { profile: "user", security: "shield", notifications: "bell", keys: "key", team: "users", plan: "crown" } as const;
  return (
    <div className="rise">
      <PageHeader eyebrow={t("eyebrow")} title={t("title")} />
      <Tabs
        value={tab}
        onChange={(v) => router.replace(`${pathname}?tab=${v}`)}
        options={TABS.map((k) => ({ value: k, label: t(`tab_${k}`), icon: icons[k] }))}
      />
      {tab === "profile" && <Profile />}
      {tab === "security" && <Security />}
      {tab === "notifications" && <Notifications />}
      {tab === "keys" && <Keys />}
      {tab === "team" && <Team />}
      {tab === "plan" && <PlanTab />}
    </div>
  );
}

/* ---------------- profile ---------------- */
function Profile() {
  const t = useTranslations("settings");
  const locale = useLocale() as Locale;
  const { me, setMe } = useMe();
  const toast = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const [name, setName] = useState(me.user.name);
  const [loc, setLoc] = useState<Locale>(me.user.locale);
  const [cur, setCur] = useState("");
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const saveProfile = async () => {
    setBusy(true);
    try {
      const m = await api.updateMe({ name: name.trim(), locale: loc });
      setMe(m);
      toast(t("saved"));
      if (loc !== locale) router.replace(`${pathname}?tab=profile`, { locale: loc });
    } catch (e) {
      toast(errorText(e, locale), "err");
    } finally {
      setBusy(false);
    }
  };
  const savePw = async () => {
    setErr("");
    if (pw.length < 8) return setErr(t("pw_short"));
    setBusy(true);
    try {
      await api.updateMe({ password: pw, current_password: cur });
      setCur("");
      setPw("");
      toast(t("pw_changed"));
    } catch (e) {
      setErr(errorText(e, locale));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardTitle>{t("profile")}</CardTitle>
        <div className="space-y-3">
          <Input label={t("name")} value={name} onChange={(e) => setName(e.target.value)} />
          <Input label={t("email")} value={me.user.email} readOnly dir="ltr" className="opacity-70" />
          <div>
            <div className="mb-1.5 text-[13px] text-muted">{t("language")}</div>
            <Segmented<Locale> value={loc} onChange={setLoc} options={[{ value: "ar", label: "العربية" }, { value: "en", label: "English" }]} />
          </div>
          <Button onClick={saveProfile} loading={busy} disabled={!name.trim() || (name.trim() === me.user.name && loc === me.user.locale)}>
            {t("save")}
          </Button>
        </div>
      </Card>
      <Card>
        <CardTitle>{t("password")}</CardTitle>
        <div className="space-y-3">
          <Input label={t("current_password")} type="password" autoComplete="current-password" dir="ltr" value={cur} onChange={(e) => setCur(e.target.value)} />
          <Input label={t("new_password")} type="password" autoComplete="new-password" dir="ltr" hint={t("pw_hint")} value={pw} onChange={(e) => setPw(e.target.value)} />
          {err && <p role="alert" className="text-sm text-red">{err}</p>}
          <Button onClick={savePw} loading={busy} disabled={!cur || !pw}>
            {t("change_password")}
          </Button>
        </div>
      </Card>
    </div>
  );
}

/* ---------------- security / 2FA ---------------- */
function Security() {
  const t = useTranslations("settings");
  const locale = useLocale() as Locale;
  const { me, refresh } = useMe();
  const toast = useToast();
  const [setup, setSetup] = useState<{ secret: string; otpauth_url: string } | null>(null);
  const [qr, setQr] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!setup) return;
    let on = true;
    QRCode.toDataURL(setup.otpauth_url, { margin: 1, width: 220, color: { dark: "#111111", light: "#ffffff" } }).then((u) => on && setQr(u));
    return () => {
      on = false;
    };
  }, [setup]);

  const start = async () => {
    setBusy(true);
    setErr("");
    try {
      setSetup(await api.totpSetup());
    } catch (e) {
      setErr(errorText(e, locale));
    } finally {
      setBusy(false);
    }
  };
  const enable = async () => {
    setBusy(true);
    setErr("");
    try {
      await api.totpEnable(code);
      setSetup(null);
      setCode("");
      await refresh();
      toast(t("totp_enabled"));
    } catch (e) {
      setErr(errorText(e, locale));
    } finally {
      setBusy(false);
    }
  };
  const disable = async () => {
    setBusy(true);
    setErr("");
    try {
      await api.totpDisable(code);
      setCode("");
      await refresh();
      toast(t("totp_disabled"));
    } catch (e) {
      setErr(errorText(e, locale));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="max-w-2xl">
      <CardTitle aside={me.user.totp_enabled ? <Badge tone="green">{t("on")}</Badge> : <Badge>{t("off")}</Badge>}>{t("twofa")}</CardTitle>
      <p className="mb-4 text-sm text-muted">{t("twofa_text")}</p>
      {!me.user.totp_enabled && !setup && (
        <Button icon="shield" onClick={start} loading={busy}>
          {t("twofa_setup")}
        </Button>
      )}
      {!me.user.totp_enabled && setup && (
        <div className="grid gap-5 sm:grid-cols-[auto_1fr]">
          <div className="mx-auto">
            <div className="grid h-[236px] w-[236px] place-items-center rounded-2xl bg-white p-2">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              {qr ? <img src={qr} alt={t("qr_alt")} width={220} height={220} /> : <Skeleton className="h-[220px] w-[220px]" />}
            </div>
          </div>
          <div className="space-y-3">
            <p className="text-sm">{t("twofa_scan")}</p>
            <div>
              <div className="mb-1 text-xs text-muted">{t("twofa_manual")}</div>
              <code dir="ltr" className="block break-all rounded-lg border border-line bg-bg2 px-3 py-2 text-sm tracking-wider">{setup.secret}</code>
            </div>
            <Input label={t("twofa_code")} inputMode="numeric" maxLength={6} dir="ltr" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} className="text-center text-lg tracking-[.4em]" />
            {err && <p role="alert" className="text-sm text-red">{err}</p>}
            <div className="flex gap-2">
              <Button variant="ghost" onClick={() => { setSetup(null); setCode(""); setErr(""); }}>{t("cancel")}</Button>
              <Button onClick={enable} loading={busy} disabled={code.length < 6}>{t("twofa_enable")}</Button>
            </div>
          </div>
        </div>
      )}
      {me.user.totp_enabled && (
        <div className="max-w-xs space-y-3">
          <Input label={t("twofa_code_disable")} inputMode="numeric" maxLength={6} dir="ltr" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} className="text-center text-lg tracking-[.4em]" />
          {err && <p role="alert" className="text-sm text-red">{err}</p>}
          <Button variant="danger" onClick={disable} loading={busy} disabled={code.length < 6}>
            {t("twofa_disable")}
          </Button>
        </div>
      )}
    </Card>
  );
}

/* ---------------- notifications ---------------- */
function Notifications() {
  const t = useTranslations("settings");
  const locale = useLocale() as Locale;
  const { me } = useMe();
  const toast = useToast();
  const writable = canWrite(me);
  const feats = me.tenant.plan.features;
  const ch = useApi(`channels:${me.tenant.id}`, () => api.channels());
  const [link, setLink] = useState<{ code: string; bot_username: string; deep_link: string } | null>(null);
  const [email, setEmail] = useState({ enabled: false, address: "" });
  const [hook, setHook] = useState({ enabled: false, url: "" });
  const [busy, setBusy] = useState("");

  useEffect(() => {
    if (!ch.data) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setEmail({ enabled: ch.data.email.enabled, address: ch.data.email.address ?? "" });
    setHook({ enabled: ch.data.webhook.enabled, url: ch.data.webhook.url ?? "" });
  }, [ch.data]);

  const run = async (key: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(key);
    try {
      await fn();
      toast(ok);
      if (key !== "test") await ch.mutate();
    } catch (e) {
      toast(errorText(e, locale), "err");
    } finally {
      setBusy("");
    }
  };
  const test = (c: string) => run(`test:${c}`, () => api.testChannel(c), t("test_sent"));

  if (ch.isLoading) return <Skeleton className="h-64 w-full" />;
  if (ch.error) return <ErrorState error={ch.error} onRetry={() => ch.mutate()} />;
  const linked = ch.data?.telegram.linked;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardTitle aside={linked ? <Badge tone="green">{t("linked")}</Badge> : <Badge>{t("not_linked")}</Badge>}>
          <span className="inline-flex items-center gap-2"><Icon name="send" size={16} className="text-blue" />{t("telegram")}</span>
        </CardTitle>
        <p className="mb-3 text-sm text-muted">{linked ? t("tg_linked", { chat: ch.data?.telegram.chat_title || "—" }) : t("tg_text")}</p>
        {writable && linked && (ch.data?.telegram.chats?.length ?? 0) > 0 && (
          <ul className="mb-3 divide-y divide-line rounded-xl border border-line text-sm">
            {ch.data?.telegram.chats?.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-2 px-3 py-2">
                <span className="truncate">{c.title || c.id}</span>
                <button className="text-xs text-red" disabled={busy === `unlink:${c.id}`}
                  onClick={() => run(`unlink:${c.id}`, async () => ch.mutate(await api.telegramUnlink(c.id), false), t("tg_unlinked"))}>
                  {t("tg_unlink")}
                </button>
              </li>
            ))}
          </ul>
        )}
        {link && !linked && (
          <div className="mb-3 space-y-2 rounded-xl border border-line bg-bg2 p-3 text-sm">
            <a href={link.deep_link} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-lg bg-[#2a9ad8] px-4 py-2 font-medium text-white">
              <Icon name="external" size={15} />
              {t("tg_open", { bot: link.bot_username })}
            </a>
            <div className="text-xs text-muted">{t("tg_manual")}</div>
            <code dir="ltr" className="block rounded-md border border-line px-2 py-1">/start {link.code}</code>
            <button className="text-xs text-accent" onClick={() => ch.mutate()}>{t("tg_check")}</button>
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          {writable && (
            <Button variant={linked ? "ghost" : "primary"} icon="link" loading={busy === "tg"} onClick={() => run("tg", async () => setLink(await api.telegramLink()), t("tg_link_ready"))}>
              {linked ? t("tg_relink") : t("tg_link")}
            </Button>
          )}
          {linked && (
            <Button variant="ghost" size="md" loading={busy === "test:telegram"} onClick={() => test("telegram")}>
              {t("test")}
            </Button>
          )}
        </div>
      </Card>

      <Card>
        <CardTitle aside={feats.includes("email") ? undefined : <Badge tone="gold"><Icon name="lock" size={11} />{t("locked")}</Badge>}>
          <span className="inline-flex items-center gap-2"><Icon name="mail" size={16} className="text-accent" />{t("email_ch")}</span>
        </CardTitle>
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3 text-sm">
            {t("enable_channel")}
            <Switch checked={email.enabled} label={t("enable_channel")} disabled={!writable || !feats.includes("email")} onChange={(v) => setEmail({ ...email, enabled: v })} />
          </div>
          <Input label={t("email_address")} type="email" dir="ltr" disabled={!writable || !feats.includes("email")} value={email.address} onChange={(e) => setEmail({ ...email, address: e.target.value })} />
          <div className="flex flex-wrap gap-2">
            <Button loading={busy === "email"} disabled={!writable || !feats.includes("email")} onClick={() => run("email", () => api.updateChannels({ email }), t("saved"))}>{t("save")}</Button>
            <Button variant="ghost" disabled={!feats.includes("email") || !ch.data?.email.enabled} loading={busy === "test:email"} onClick={() => test("email")}>{t("test")}</Button>
          </div>
        </div>
      </Card>

      <Card className="lg:col-span-2">
        <CardTitle aside={feats.includes("webhook") ? undefined : <Badge tone="gold"><Icon name="lock" size={11} />{t("locked")}</Badge>}>
          <span className="inline-flex items-center gap-2"><Icon name="link" size={16} className="text-green" />{t("webhook_ch")}</span>
        </CardTitle>
        <p className="mb-3 text-sm text-muted">{t("webhook_text")}</p>
        <div className="grid gap-3 sm:grid-cols-[auto_1fr] sm:items-end">
          <div className="flex items-center gap-3 text-sm sm:pb-2.5">
            <Switch checked={hook.enabled} label={t("enable_channel")} disabled={!writable || !feats.includes("webhook")} onChange={(v) => setHook({ ...hook, enabled: v })} />
            {t("enable_channel")}
          </div>
          <Input label="URL" type="url" dir="ltr" placeholder="https://example.com/hook" disabled={!writable || !feats.includes("webhook")} value={hook.url} onChange={(e) => setHook({ ...hook, url: e.target.value })} />
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button loading={busy === "webhook"} disabled={!writable || !feats.includes("webhook")} onClick={() => run("webhook", () => api.updateChannels({ webhook: hook }), t("saved"))}>{t("save")}</Button>
          <Button variant="ghost" disabled={!feats.includes("webhook") || !ch.data?.webhook.enabled} loading={busy === "test:webhook"} onClick={() => test("webhook")}>{t("test")}</Button>
        </div>
      </Card>
    </div>
  );
}

/* ---------------- API keys ---------------- */
function Keys() {
  const t = useTranslations("settings");
  const locale = useLocale() as Locale;
  const { me } = useMe();
  const toast = useToast();
  const writable = canWrite(me);
  const { data, error, isLoading, mutate } = useApi(`keys:${me.tenant.id}`, () => api.apiKeys());
  const [name, setName] = useState("");
  const [created, setCreated] = useState<ApiKey | null>(null);
  const [del, setDel] = useState<ApiKey | null>(null);
  const [busy, setBusy] = useState(false);
  const [origin, setOrigin] = useState("https://energy.example.com");
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOrigin(window.location.origin);
  }, []);

  if (error instanceof ApiError && error.code === "feature_not_in_plan") return <Upsell feature="api" />;

  const create = async () => {
    setBusy(true);
    try {
      const k = await api.createApiKey(name.trim());
      setCreated(k);
      setName("");
      await mutate();
    } catch (e) {
      toast(errorText(e, locale), "err");
    } finally {
      setBusy(false);
    }
  };
  const copy = (s: string) => navigator.clipboard?.writeText(s).then(() => toast(t("copied")), () => {});
  const keyShown = created?.key ?? "se_live_xxxxxxxx";
  const cmd = `claude mcp add --transport http syriana-energy ${origin}/mcp --header "Authorization: Bearer ${keyShown}"`;
  const json = `{\n  "mcpServers": {\n    "syriana-energy": {\n      "type": "http",\n      "url": "${origin}/mcp",\n      "headers": { "Authorization": "Bearer ${keyShown}" }\n    }\n  }\n}`;
  const list = items(data);

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardTitle>{t("keys_title")}</CardTitle>
        <p className="mb-3 text-sm text-muted">{t("keys_text")}</p>
        {writable && (
          <form onSubmit={(e) => { e.preventDefault(); create(); }} className="mb-4 flex items-end gap-2">
            <div className="flex-1"><Input label={t("key_name")} placeholder={t("key_ph")} value={name} onChange={(e) => setName(e.target.value)} /></div>
            <Button type="submit" icon="plus" loading={busy} disabled={!name.trim()}>{t("create")}</Button>
          </form>
        )}
        {isLoading && <Skeleton className="h-20 w-full" />}
        {error && !(error instanceof ApiError && error.code === "feature_not_in_plan") && <ErrorState error={error} onRetry={() => mutate()} />}
        {!isLoading && list.length === 0 && <p className="py-4 text-center text-sm text-muted">{t("no_keys")}</p>}
        <ul className="divide-y divide-line">
          {list.map((k) => (
            <li key={k.id} className="flex items-center justify-between gap-3 py-2.5">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">{k.name}</div>
                <div className="text-xs text-muted">{k.created_at ? fmtDate(k.created_at, locale) : ""}</div>
              </div>
              {writable && <Button size="sm" variant="danger" onClick={() => setDel(k)}>{t("revoke")}</Button>}
            </li>
          ))}
        </ul>
      </Card>

      <Card>
        <CardTitle>{t("mcp_title")}</CardTitle>
        <p className="mb-3 text-sm text-muted">{t("mcp_text")}</p>
        <Snippet label={t("mcp_cli")} code={cmd} onCopy={() => copy(cmd)} copyLabel={t("copy")} />
        <Snippet label={t("mcp_json")} code={json} onCopy={() => copy(json)} copyLabel={t("copy")} />
        <p className="text-xs text-muted">{t("mcp_tools")} <code dir="ltr" className="inline-block">list_devices, get_live_status, get_today_summary, get_history, list_alerts, get_settings, change_setting</code></p>
      </Card>

      <Modal
        open={!!created}
        onClose={() => setCreated(null)}
        title={t("key_created")}
        footer={<Button className="flex-1" onClick={() => setCreated(null)}>{t("done")}</Button>}
      >
        <p className="mb-3 flex items-start gap-1.5 text-sm text-gold"><Icon name="warn" size={16} className="mt-0.5 shrink-0" />{t("key_once")}</p>
        <code dir="ltr" className="block break-all rounded-lg border border-line bg-bg2 px-3 py-2.5 text-sm">{created?.key}</code>
        <Button className="mt-3" variant="ghost" icon="copy" onClick={() => created?.key && copy(created.key)}>{t("copy")}</Button>
      </Modal>
      <ConfirmModal
        open={!!del}
        danger
        title={t("revoke_title")}
        text={t("revoke_text", { name: del?.name ?? "" })}
        confirmLabel={t("revoke")}
        onClose={() => setDel(null)}
        onConfirm={async () => {
          if (!del) return;
          try {
            await api.deleteApiKey(del.id);
            await mutate();
          } catch (e) {
            toast(errorText(e, locale), "err");
          }
          setDel(null);
        }}
      />
    </div>
  );
}

function Snippet({ label, code, onCopy, copyLabel }: { label: string; code: string; onCopy: () => void; copyLabel: string }) {
  return (
    <div className="mb-3">
      <div className="mb-1 flex items-center justify-between text-xs text-muted">
        {label}
        <button onClick={onCopy} className="inline-flex items-center gap-1 text-accent"><Icon name="copy" size={12} />{copyLabel}</button>
      </div>
      <pre dir="ltr" className="overflow-x-auto whitespace-pre-wrap break-all rounded-lg border border-line bg-bg2 p-3 text-start text-xs leading-relaxed">{code}</pre>
    </div>
  );
}

/* ---------------- team ---------------- */
function Team() {
  const t = useTranslations("settings");
  const locale = useLocale() as Locale;
  const { me } = useMe();
  const toast = useToast();
  const writable = canWrite(me);
  const { data, error, isLoading, mutate } = useApi(`users:${me.tenant.id}`, () => api.users());
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ email: "", name: "", role: "viewer", password: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [del, setDel] = useState<TeamUser | null>(null);
  const list = items(data);

  const add = async () => {
    setBusy(true);
    setErr("");
    try {
      await api.createUser(f);
      setOpen(false);
      setF({ email: "", name: "", role: "viewer", password: "" });
      await mutate();
    } catch (e) {
      setErr(errorText(e, locale));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card>
      <CardTitle aside={writable && <Button size="sm" icon="plus" onClick={() => setOpen(true)}>{t("add_user")}</Button>}>{t("team_title")}</CardTitle>
      {isLoading && <Skeleton className="h-24 w-full" />}
      {error && <ErrorState error={error} onRetry={() => mutate()} />}
      <ul className="divide-y divide-line">
        {list.map((u) => (
          <li key={u.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
            <div className="flex min-w-0 items-center gap-3">
              <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-line bg-panel text-sm font-semibold">{u.name.slice(0, 1).toUpperCase()}</div>
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">{u.name}{u.id === me.user.id && <span className="ms-2 text-xs text-muted">({t("you")})</span>}</div>
                <div dir="ltr" className="truncate text-start text-xs text-muted">{u.email}</div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {writable && u.id !== me.user.id && u.role !== "owner" ? (
                <Select aria-label={t("role")} value={u.role} className="!w-32 !py-1.5" onChange={async (e) => { try { await api.updateUser(u.id, { role: e.target.value }); await mutate(); } catch (x) { toast(errorText(x, locale), "err"); } }}>
                  <option value="admin">{t("role_admin")}</option>
                  <option value="viewer">{t("role_viewer")}</option>
                </Select>
              ) : (
                <Badge tone={u.role === "owner" ? "accent" : "muted"}>{t(`role_${u.role}`)}</Badge>
              )}
              {writable && u.id !== me.user.id && u.role !== "owner" && (
                <Button size="sm" variant="danger" aria-label={t("remove_user")} onClick={() => setDel(u)}><Icon name="trash" size={15} /></Button>
              )}
            </div>
          </li>
        ))}
      </ul>
      <Modal open={open} onClose={() => setOpen(false)} title={t("add_user")} footer={<><Button variant="ghost" className="flex-1" onClick={() => setOpen(false)}>{t("cancel")}</Button><Button className="flex-1" loading={busy} disabled={!f.email || !f.name || f.password.length < 8} onClick={add}>{t("create")}</Button></>}>
        <div className="space-y-3">
          <Input label={t("name")} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} data-autofocus />
          <Input label={t("email")} type="email" dir="ltr" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
          <Select label={t("role")} value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
            <option value="viewer">{t("role_viewer")}</option>
            <option value="admin">{t("role_admin")}</option>
          </Select>
          <Input label={t("password")} type="password" dir="ltr" autoComplete="new-password" hint={t("pw_hint")} value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
          {err && <p role="alert" className="text-sm text-red">{err}</p>}
        </div>
      </Modal>
      <ConfirmModal open={!!del} danger title={t("remove_user")} text={del?.name} confirmLabel={t("delete")} onClose={() => setDel(null)} onConfirm={async () => { if (!del) return; try { await api.deleteUser(del.id); await mutate(); } catch (e) { toast(errorText(e, locale), "err"); } setDel(null); }} />
    </Card>
  );
}

/* ---------------- plan & usage ---------------- */
function PlanTab() {
  const t = useTranslations("settings");
  const f = useTranslations("features");
  const locale = useLocale() as Locale;
  const { me } = useMe();
  const branding = useBranding();
  const usage = useApi(`usage:${me.tenant.id}`, () => api.usage());
  const plans = useApi("plans", () => api.plans());
  const [period, setPeriod] = useState<"month" | "year">("month");
  const p = me.tenant.plan;
  const u = usage.data;
  const pct = u ? Math.min(100, Math.round((u.devices / Math.max(1, u.max_devices)) * 100)) : 0;
  const all = ["control", "ai", "email", "webhook", "automations", "api", "white_label", "customers"] as const;
  const order = ["free", "home", "pro", "installer"];
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardTitle aside={<Badge tone="accent">{locale === "ar" ? p.name_ar : p.name}</Badge>}>{t("current_plan")}</CardTitle>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div><dt className="text-muted">{t("expires")}</dt><dd>{me.tenant.plan_expires_at ? fmtDate(me.tenant.plan_expires_at, locale) : t("no_expiry")}</dd></div>
            <div><dt className="text-muted">{t("history_days")}</dt><dd><span dir="ltr" className="num">{p.history_days}</span> {t("days")}</dd></div>
          </dl>
          <div className="mt-4 flex flex-wrap gap-1.5">
            {all.map((k) => (
              <span key={k} className={cx("inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs", p.features.includes(k) ? "border-[color-mix(in_srgb,var(--green)_50%,transparent)] text-green" : "border-line text-muted/60 line-through")}>
                <Icon name={p.features.includes(k) ? "check" : "x"} size={11} />
                {f(k)}
              </span>
            ))}
          </div>
        </Card>
        <Card>
          <CardTitle>{t("usage")}</CardTitle>
          {usage.isLoading ? <Skeleton className="h-16 w-full" /> : usage.error ? <ErrorState error={usage.error} onRetry={() => usage.mutate()} /> : (
            <>
              <div className="mb-1.5 flex items-baseline justify-between text-sm"><span>{t("devices_used")}</span><b dir="ltr" className="num">{u?.devices} / {u?.max_devices}</b></div>
              <div className="h-2.5 overflow-hidden rounded-full bg-panel-hi" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
                <div className={cx("h-full rounded-full", pct >= 100 ? "bg-red" : "bg-accent")} style={{ width: `${pct}%` }} />
              </div>
              <p className="mt-3 text-xs text-muted">{t("upgrade_note")}{branding.support_email && <> <a className="text-accent" dir="ltr" href={`mailto:${branding.support_email}`}>{branding.support_email}</a></>}</p>
            </>
          )}
        </Card>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">{t("all_plans")}</h2>
        <Segmented className="w-56" label={t("billing")} value={period} onChange={setPeriod} options={[{ value: "month", label: t("monthly") }, { value: "year", label: t("yearly") }]} />
      </div>
      <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
        {(plans.data ?? []).slice().sort((a, b) => order.indexOf(a.code) - order.indexOf(b.code)).map((pl) => (
          <PlanCard key={pl.code} p={pl} period={period} locale={locale} f={(k) => f(k)} current={pl.code === p.code} />
        ))}
      </div>
    </div>
  );
}
