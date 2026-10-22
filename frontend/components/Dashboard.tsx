"use client";

import { useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { api, items, type Alert, type Locale, type LiveStatus, type TodaySummary } from "@/lib/api";
import { useApi, useDevices, useMe } from "@/lib/hooks";
import { fmt, fmtHours, fmtTime, isNum, startOfDay, timeAgoSeconds } from "@/lib/format";
import { FlowDiagram } from "./FlowDiagram";
import { Legend, TimeChart, type Series } from "./charts";
import { DevicePicker } from "./DevicePicker";
import { NoDevices } from "./NoDevices";
import { Icon, type IconName } from "./Icon";
import { Card, CardTitle, Dot, ErrorState, Eyebrow, Num, Skeleton, cx } from "./ui";

function useNow(ms = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const i = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(i);
  }, [ms]);
  return now;
}

export function Dashboard() {
  const t = useTranslations("dash");
  const { devices, selected, loading, error, reload } = useDevices();

  if (loading) return <DashSkeleton />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!selected || devices.length === 0)
    return (
      <>
        <Eyebrow>{t("now")}</Eyebrow>
        <h1 className="mb-5 text-3xl font-bold">{t("welcome")}</h1>
        <NoDevices />
      </>
    );
  return <DashboardFor key={selected.id} id={selected.id} />;
}

function DashSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-10 w-72" />
      <Skeleton className="h-[420px] w-full" />
      <div className="grid grid-cols-2 gap-3.5 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-28" />
        ))}
      </div>
    </div>
  );
}

function headlineKey(live: LiveStatus | undefined): string {
  if (!live || !live.online) return "offline";
  const m = live.metrics;
  if (m.mode === "fault" || (m.fault_codes && m.fault_codes.length)) return "fault";
  const pv = m.pv_power ?? 0;
  const bp = m.battery_power ?? 0;
  if (pv > 50 && bp > 50) return "solar_charging";
  if (pv > 50 && bp < -50) return "solar_battery";
  if (pv > 50) return "solar";
  if (m.grid_available) return "grid";
  if (bp < -50) return "battery";
  return "idle";
}

function DashboardFor({ id }: { id: string }) {
  const t = useTranslations("dash");
  const f = useTranslations("flow");
  const locale = useLocale() as Locale;
  const { selected } = useDevices();
  const { me } = useMe();
  const now = useNow();

  const live = useApi(`live:${id}`, () => api.live(id), { refreshInterval: 15000, keepPreviousData: false });
  const today = useApi(`today:${id}`, () => api.today(id), { refreshInterval: 60000 });
  const alerts = useApi(`alerts:dash:${me.tenant.id}`, () => api.alerts({ limit: 5 }), { refreshInterval: 60000 });

  const m = live.data?.metrics;
  const online = !!live.data?.online;
  const age = timeAgoSeconds(live.data?.ts, now);
  const hk = headlineKey(live.data);
  const mode = m?.mode ?? "unknown";

  const pv = m?.pv_power ?? null;
  const load = m?.load_power ?? null;
  const sub = (() => {
    if (!live.data) return "";
    if (!online) return t("sub_offline");
    const parts: string[] = [];
    parts.push(m?.grid_available === true ? t("sub_grid_on") : m?.grid_available === false ? t("sub_grid_off") : "");
    if (isNum(pv) && isNum(load) && load > 0 && pv > load * 1.2) parts.push(t("sub_pv_ratio", { x: fmt(pv / load, 1) }));
    return parts.filter(Boolean).join(t("sep"));
  })();

  return (
    <div className="rise">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Eyebrow>{t("now")}</Eyebrow>
        <div className="flex flex-wrap items-center gap-2">
          <DevicePicker />
          <span className="inline-flex items-center gap-2 rounded-full border border-line bg-panel px-3 py-1.5 text-[13px] text-muted">
            <Dot on={online} />
            {live.isLoading ? "…" : online ? t("connected") : t("disconnected")}
            <span className="opacity-50">·</span>
            {t("last_update")}{" "}
            <b className="font-semibold text-fg" suppressHydrationWarning>
              {age === null ? "—" : age < 2 ? t("just_now") : t("seconds_ago", { n: age })}
            </b>
          </span>
        </div>
      </div>

      <h1 className="mt-1 bg-gradient-to-r from-fg to-accent bg-clip-text text-[clamp(28px,4.6vw,46px)] font-bold leading-tight tracking-tight text-transparent rtl:bg-gradient-to-l">
        {live.isLoading ? <Skeleton className="mt-2 h-10 w-96 max-w-full" /> : t(`headline_${hk}`)}
      </h1>
      <p className="min-h-6 text-muted">{sub}</p>
      {online && (
        <span className="mt-2.5 inline-flex items-center gap-2 rounded-full border border-[color-mix(in_srgb,var(--accent2)_35%,transparent)] bg-[color-mix(in_srgb,var(--accent2)_12%,transparent)] px-3.5 py-1.5 text-sm text-gold">
          <Icon name="battery" size={14} />
          {f(`mode_chip_${mode}`)}
        </span>
      )}

      <div className="mt-4">
        {live.isLoading ? (
          <Skeleton className="h-[420px] w-full" />
        ) : live.error && !live.data ? (
          <ErrorState error={live.error} onRetry={() => live.mutate()} />
        ) : (
          <FlowDiagram metrics={m} online={online} model={selected?.model} />
        )}
      </div>

      <Stats today={today.data} loading={today.isLoading} total={m?.energy_pv_total} load={load} />

      <div className="mt-6 grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <TodayChart id={id} today={today.data} />
        <AlertsPanel alerts={items(alerts.data)} loading={alerts.isLoading} locale={locale} />
      </div>
    </div>
  );
}

function Stats({ today, loading, total, load }: { today?: TodaySummary; loading: boolean; total?: number | null; load: number | null }) {
  const t = useTranslations("dash");
  const tiles: { k: string; v: string; unit: string; note?: string; tone?: string; icon: IconName }[] = [
    { k: t("stat_pv"), v: fmt(today?.pv_kwh, 1), unit: "kWh", icon: "sun", note: t("stat_pv_note") },
    {
      k: t("stat_load"),
      v: fmt(today?.load_kwh, 1),
      unit: "kWh",
      icon: "home",
      note: isNum(today?.grid_kwh) ? t("stat_load_note", { n: fmt(today?.grid_kwh, 1) }) : undefined,
    },
    {
      k: t("stat_runtime"),
      v: fmtHours(today?.battery_runtime_hours),
      unit: isNum(today?.battery_runtime_hours) ? t("hours") : "",
      icon: "battery",
      note: isNum(load) ? t("stat_runtime_note", { w: fmt(load) }) : undefined,
    },
    { k: t("stat_total"), v: fmt(total, 0), unit: "kWh", icon: "bolt", note: t("stat_total_note") },
  ];
  return (
    <div className="mt-4 grid grid-cols-2 gap-3 sm:gap-3.5 lg:grid-cols-4">
      {tiles.map((s) => (
        <div key={s.k} className="rounded-2xl border border-line bg-panel p-4 sm:p-[18px]">
          <div className="text-[13px] text-muted">{s.k}</div>
          {loading ? (
            <Skeleton className="mt-2 h-9 w-24" />
          ) : (
            <div className="mt-0.5 text-[28px] font-bold leading-tight tracking-tight sm:text-4xl">
              <Num v={s.v} />
              {s.unit && <small className="ms-1.5 text-[15px] font-medium text-muted">{s.unit}</small>}
            </div>
          )}
          {s.note && <div className="mt-0.5 text-xs text-muted">{s.note}</div>}
        </div>
      ))}
    </div>
  );
}

function TodayChart({ id, today }: { id: string; today?: TodaySummary }) {
  const t = useTranslations("dash");
  const locale = useLocale() as Locale;
  const now = useNow(60000);
  const day0 = useMemo(() => startOfDay().getTime(), []);
  const t1 = day0 + 24 * 3600_000;
  const hist = useApi(`hist:today:${id}`, () => api.history(id, { from: new Date(day0).toISOString(), to: new Date(t1).toISOString(), metrics: "pv_power,load_power,battery_soc", bucket: "5m" }), {
    refreshInterval: 300000,
  });
  const conv = (k: string) => (hist.data?.series?.[k] ?? []).map(([ts, v]) => [Date.parse(ts), v] as [number, number | null]);
  const series: Series[] = [
    { key: "pv", label: t("legend_pv"), color: "var(--gold)", kind: "area", unit: "W", data: conv("pv_power") },
    { key: "load", label: t("legend_load"), color: "var(--accent)", kind: "line", unit: "W", data: conv("load_power") },
    { key: "soc", label: t("legend_soc"), color: "var(--green)", kind: "line", dashed: true, axis: "r", unit: "%", data: conv("battery_soc") },
  ];
  const bands = (today?.grid_outages ?? []).map((o) => ({ from: Date.parse(o.from), to: o.to ? Date.parse(o.to) : now, color: "var(--red)" }));
  const dateStr = new Date().toLocaleDateString(locale === "ar" ? "ar-SY-u-nu-latn" : "en-GB", { day: "numeric", month: "long", year: "numeric" });
  return (
    <Card>
      <CardTitle aside={dateStr}>{t("chart_title")}</CardTitle>
      {hist.isLoading ? (
        <Skeleton className="h-[260px] w-full" />
      ) : hist.error ? (
        <ErrorState error={hist.error} onRetry={() => hist.mutate()} />
      ) : (
        <TimeChart series={series} t0={day0} t1={t1} bands={bands} now={now} emptyText={t("no_data")} />
      )}
      <Legend items={[{ label: t("legend_pv"), color: "var(--gold)" }, { label: t("legend_load"), color: "var(--accent)" }, { label: t("legend_soc"), color: "var(--green)" }, { label: t("legend_outage"), color: "var(--red)" }]} />
    </Card>
  );
}

const SEV: Record<string, { c: string; icon: IconName }> = {
  critical: { c: "var(--red)", icon: "bolt" },
  warning: { c: "var(--gold)", icon: "warn" },
  info: { c: "var(--green)", icon: "check" },
};
export function alertIcon(a: Pick<Alert, "type" | "severity">): { c: string; icon: IconName } {
  const byType: Record<string, IconName> = { grid_lost: "bolt", grid_restored: "check", battery_low: "battery", battery_full: "battery", overload: "chart", fault: "warn", device_offline: "warn", high_temperature: "warn", daily_summary: "info" };
  const base = SEV[a.severity] ?? SEV.info;
  return { c: base.c, icon: byType[a.type] ?? base.icon };
}

function AlertsPanel({ alerts, loading, locale }: { alerts: Alert[]; loading: boolean; locale: Locale }) {
  const t = useTranslations("dash");
  return (
    <Card>
      <CardTitle aside={<Link href="/app/alerts" className="text-accent">{t("all")}</Link>}>{t("alerts")}</CardTitle>
      {loading && (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-12" />
          ))}
        </div>
      )}
      {!loading && alerts.length === 0 && (
        <div className="grid place-items-center py-10 text-center text-sm text-muted">
          <Icon name="check" size={26} className="mb-2 text-green" />
          {t("no_alerts")}
        </div>
      )}
      {alerts.map((a) => {
        const s = alertIcon(a);
        return (
          <div key={a.id} className="flex items-start gap-3 border-b border-dashed border-line py-2.5 last:border-0">
            <div className="grid h-[34px] w-[34px] shrink-0 place-items-center rounded-[10px]" style={{ background: `color-mix(in srgb, ${s.c} 14%, transparent)`, color: s.c }}>
              <Icon name={s.icon} size={17} />
            </div>
            <div className="min-w-0">
              <b className={cx("block text-sm", !a.read && "text-fg")}>{locale === "ar" ? a.title_ar || a.title : a.title}</b>
              <small className="text-xs text-muted">
                <span dir="ltr" className="num">{fmtTime(a.created_at, locale)}</span> · {locale === "ar" ? a.body_ar || a.body : a.body}
              </small>
            </div>
          </div>
        );
      })}
    </Card>
  );
}
