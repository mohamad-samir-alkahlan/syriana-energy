"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { api, items, type AdminTenant, type Feature, type Locale, type Plan } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { fmt, fmtDate } from "@/lib/format";
import { BarChart } from "./charts";
import { Icon } from "./Icon";
import { useToast } from "./Providers";
import { Badge, Button, Card, CardTitle, ConfirmModal, ErrorState, Input, Modal, PageHeader, Select, Skeleton, Tabs, cx, errorText } from "./ui";

type Tab = "overview" | "tenants" | "plans";

export function Admin() {
  const t = useTranslations("admin");
  const [tab, setTab] = useState<Tab>("overview");
  return (
    <div className="rise">
      <PageHeader eyebrow={t("eyebrow")} title={t("title")} />
      <Tabs
        value={tab}
        onChange={setTab}
        options={[
          { value: "overview", label: t("tab_overview"), icon: "chart" },
          { value: "tenants", label: t("tab_tenants"), icon: "users" },
          { value: "plans", label: t("tab_plans"), icon: "crown" },
        ]}
      />
      {tab === "overview" && <Overview />}
      {tab === "tenants" && <Tenants />}
      {tab === "plans" && <Plans />}
    </div>
  );
}

function Overview() {
  const t = useTranslations("admin");
  const locale = useLocale() as Locale;
  const { data, error, isLoading, mutate } = useApi("admin:stats", () => api.adminStats());
  if (isLoading) return <Skeleton className="h-96 w-full" />;
  if (error) return <ErrorState error={error} onRetry={() => mutate()} />;
  if (!data) return null;
  const tiles = [
    { k: t("tenants"), v: fmt(data.tenants), icon: "users" as const },
    { k: t("users"), v: fmt(data.users), icon: "user" as const },
    { k: t("devices"), v: `${fmt(data.devices_online)} / ${fmt(data.devices)}`, icon: "device" as const, note: t("online_of") },
    { k: t("mrr"), v: `$${fmt(data.mrr_estimate)}`, icon: "crown" as const, note: t("mrr_note") },
  ];
  const groups = data.signups_30d.map(([d, n]) => ({
    label: new Date(d + "T00:00:00").toLocaleDateString(locale === "ar" ? "ar-SY-u-nu-latn" : "en-GB", { day: "numeric", month: "short" }),
    values: [{ key: "n", v: n, color: "var(--accent)", name: t("signups") }],
  }));
  const planTotal = Object.values(data.by_plan).reduce((a, b) => a + b, 0) || 1;
  const colors: Record<string, string> = { free: "var(--muted)", home: "var(--blue)", pro: "var(--green)", installer: "var(--accent)" };
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {tiles.map((x) => (
          <div key={x.k} className="rounded-2xl border border-line bg-panel p-4">
            <div className="flex items-center gap-2 text-[13px] text-muted"><Icon name={x.icon} size={15} className="text-accent" />{x.k}</div>
            <div className="mt-1 text-3xl font-bold tracking-tight"><span dir="ltr" className="num">{x.v}</span></div>
            {x.note && <div className="text-xs text-muted">{x.note}</div>}
          </div>
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <Card>
          <CardTitle aside={t("last30")}>{t("signups_chart")}</CardTitle>
          <BarChart groups={groups} unit="" height={220} emptyText={t("no_data")} />
        </Card>
        <Card>
          <CardTitle>{t("by_plan")}</CardTitle>
          <div className="space-y-3">
            {Object.entries(data.by_plan).map(([code, n]) => (
              <div key={code}>
                <div className="mb-1 flex justify-between text-sm"><span>{code}</span><b dir="ltr" className="num">{n}</b></div>
                <div className="h-2 overflow-hidden rounded-full bg-panel-hi"><div className="h-full rounded-full" style={{ width: `${(n / planTotal) * 100}%`, background: colors[code] ?? "var(--accent)" }} /></div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

function Tenants() {
  const t = useTranslations("admin");
  const locale = useLocale() as Locale;
  const toast = useToast();
  const [q, setQ] = useState("");
  const [dq, setDq] = useState("");
  useEffect(() => {
    const id = setTimeout(() => setDq(q.trim()), 300);
    return () => clearTimeout(id);
  }, [q]);
  const { data, error, isLoading, mutate } = useApi(`admin:tenants:${dq}`, () => api.adminTenants(dq || undefined), { keepPreviousData: true });
  const plans = useApi("admin:plans", () => api.adminPlans());
  const [edit, setEdit] = useState<AdminTenant | null>(null);
  const [susp, setSusp] = useState<AdminTenant | null>(null);
  const list = items(data);

  return (
    <Card className="!p-0">
      <div className="flex flex-wrap items-center gap-3 border-b border-line p-4">
        <div className="relative min-w-0 flex-1 basis-56">
          <Input aria-label={t("search")} placeholder={t("search")} value={q} onChange={(e) => setQ(e.target.value)} type="search" />
        </div>
        <span className="text-sm text-muted">{t("count", { n: list.length })}</span>
      </div>
      {isLoading && <Skeleton className="m-4 h-40" />}
      {error && <div className="p-4"><ErrorState error={error} onRetry={() => mutate()} /></div>}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="text-xs text-muted">
            <tr>{["name", "type", "plan", "devices", "users", "created", "status", ""].map((h) => <th key={h} className="px-4 py-3 text-start font-normal">{h && t(`col_${h}`)}</th>)}</tr>
          </thead>
          <tbody>
            {list.map((x) => (
              <tr key={x.id} className="border-t border-line">
                <td className="px-4 py-3 font-medium">{x.name}</td>
                <td className="px-4 py-3 text-muted">{x.type}</td>
                <td className="px-4 py-3"><Badge tone="accent">{x.plan}</Badge></td>
                <td className="px-4 py-3"><span dir="ltr" className="num">{x.devices}</span></td>
                <td className="px-4 py-3"><span dir="ltr" className="num">{x.users}</span></td>
                <td className="px-4 py-3 text-muted">{fmtDate(x.created_at, locale)}</td>
                <td className="px-4 py-3">{x.suspended ? <Badge tone="red">{t("suspended")}</Badge> : <Badge tone="green">{t("active")}</Badge>}</td>
                <td className="px-4 py-3">
                  <div className="flex justify-end gap-2">
                    <Button size="sm" variant="ghost" icon="edit" onClick={() => setEdit(x)}>{t("edit")}</Button>
                    <Button size="sm" variant={x.suspended ? "soft" : "danger"} onClick={() => setSusp(x)}>{x.suspended ? t("unsuspend") : t("suspend")}</Button>
                  </div>
                </td>
              </tr>
            ))}
            {!isLoading && list.length === 0 && <tr><td colSpan={8} className="px-4 py-10 text-center text-muted">{t("no_tenants")}</td></tr>}
          </tbody>
        </table>
      </div>

      {edit && <EditTenant x={edit} plans={plans.data ?? []} onClose={() => setEdit(null)} onSaved={async () => { setEdit(null); await mutate(); toast(t("saved")); }} />}
      <ConfirmModal
        open={!!susp}
        danger={!susp?.suspended}
        title={susp?.suspended ? t("unsuspend_title") : t("suspend_title")}
        text={susp ? (susp.suspended ? t("unsuspend_text", { name: susp.name }) : t("suspend_text", { name: susp.name })) : ""}
        confirmLabel={susp?.suspended ? t("unsuspend") : t("suspend")}
        onClose={() => setSusp(null)}
        onConfirm={async () => {
          if (!susp) return;
          try {
            await api.adminUpdateTenant(susp.id, { suspended: !susp.suspended });
            await mutate();
          } catch (e) {
            toast(errorText(e, locale), "err");
          }
          setSusp(null);
        }}
      />
    </Card>
  );
}

function EditTenant({ x, plans, onClose, onSaved }: { x: AdminTenant; plans: Plan[]; onClose: () => void; onSaved: () => void }) {
  const t = useTranslations("admin");
  const locale = useLocale() as Locale;
  const [plan, setPlan] = useState(x.plan);
  const [exp, setExp] = useState(x.plan_expires_at ? x.plan_expires_at.slice(0, 10) : "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const save = async () => {
    setBusy(true);
    try {
      await api.adminUpdateTenant(x.id, { plan_code: plan, plan_expires_at: exp ? new Date(exp + "T23:59:59Z").toISOString() : null });
      onSaved();
    } catch (e) {
      setErr(errorText(e, locale));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open onClose={onClose} title={t("edit_tenant", { name: x.name })} footer={<><Button variant="ghost" className="flex-1" onClick={onClose}>{t("cancel")}</Button><Button className="flex-1" loading={busy} onClick={save}>{t("save")}</Button></>}>
      <div className="space-y-3">
        <Select label={t("col_plan")} value={plan} onChange={(e) => setPlan(e.target.value)}>
          {(plans.length ? plans.map((p) => p.code) : ["free", "home", "pro", "installer"]).map((c) => <option key={c} value={c}>{c}</option>)}
        </Select>
        <Input label={t("expiry")} hint={t("expiry_hint")} type="date" dir="ltr" value={exp} onChange={(e) => setExp(e.target.value)} />
        {err && <p role="alert" className="text-sm text-red">{err}</p>}
      </div>
    </Modal>
  );
}

const FEATS: Feature[] = ["control", "ai", "email", "webhook", "automations", "api", "white_label", "customers"];
function Plans() {
  const t = useTranslations("admin");
  const { data, error, isLoading, mutate } = useApi("admin:plans", () => api.adminPlans());
  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (error) return <ErrorState error={error} onRetry={() => mutate()} />;
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {(data ?? []).map((p) => <PlanEditor key={p.code} plan={p} onSaved={() => mutate()} />)}
      {data?.length === 0 && <p className="text-muted">{t("no_plans")}</p>}
    </div>
  );
}
function PlanEditor({ plan, onSaved }: { plan: Plan; onSaved: () => void }) {
  const t = useTranslations("admin");
  const f = useTranslations("features");
  const locale = useLocale() as Locale;
  const toast = useToast();
  const [p, setP] = useState(plan);
  const [busy, setBusy] = useState(false);
  const dirty = JSON.stringify(p) !== JSON.stringify(plan);
  const num = (k: "price_month" | "price_year" | "max_devices" | "history_days") => (e: React.ChangeEvent<HTMLInputElement>) => setP({ ...p, [k]: e.target.value === "" ? NaN : Number(e.target.value) });
  const save = async () => {
    setBusy(true);
    try {
      await api.adminUpdatePlan(plan.code, { price_month: p.price_month, price_year: p.price_year, max_devices: p.max_devices, history_days: p.history_days, features: p.features, name: p.name, name_ar: p.name_ar });
      toast(t("saved"));
      onSaved();
    } catch (e) {
      toast(errorText(e, locale), "err");
    } finally {
      setBusy(false);
    }
  };
  const bad = [p.price_month, p.price_year, p.max_devices, p.history_days].some((v) => !Number.isFinite(v) || v < 0);
  return (
    <Card>
      <CardTitle aside={<code dir="ltr" className="text-xs">{plan.code}</code>}>{locale === "ar" ? plan.name_ar : plan.name}</CardTitle>
      <div className="grid grid-cols-2 gap-2.5">
        <Input label={t("p_month")} type="number" dir="ltr" min={0} step="0.5" value={Number.isNaN(p.price_month) ? "" : p.price_month} onChange={num("price_month")} />
        <Input label={t("p_year")} type="number" dir="ltr" min={0} step="1" value={Number.isNaN(p.price_year) ? "" : p.price_year} onChange={num("price_year")} />
        <Input label={t("p_devices")} type="number" dir="ltr" min={0} value={Number.isNaN(p.max_devices) ? "" : p.max_devices} onChange={num("max_devices")} />
        <Input label={t("p_history")} type="number" dir="ltr" min={0} value={Number.isNaN(p.history_days) ? "" : p.history_days} onChange={num("history_days")} />
      </div>
      <div className="mt-3 space-y-1.5">
        {FEATS.map((k) => (
          <label key={k} className="flex cursor-pointer items-center gap-2 text-sm">
            <input type="checkbox" className="h-4 w-4 accent-[var(--accent)]" checked={p.features.includes(k)} onChange={(e) => setP({ ...p, features: e.target.checked ? [...p.features, k] : p.features.filter((x) => x !== k) })} />
            <span className={cx(!p.features.includes(k) && "text-muted")}>{f(k)}</span>
          </label>
        ))}
      </div>
      {dirty && <Button className="mt-4 w-full" loading={busy} disabled={bad} onClick={save}>{t("save")}</Button>}
    </Card>
  );
}
