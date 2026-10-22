"use client";

import { useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { api, type Locale } from "@/lib/api";
import { useApi, useDevices, useMe } from "@/lib/hooks";
import { downloadCsv, fmt, startOfDay, ymd } from "@/lib/format";
import { BarChart, Legend, TimeChart, type Series } from "./charts";
import { DevicePicker } from "./DevicePicker";
import { NoDevices } from "./NoDevices";
import { Button, Card, CardTitle, ErrorState, Input, PageHeader, Segmented, Skeleton, cx } from "./ui";

type Preset = "today" | "7d" | "30d" | "custom";
const METRICS = [
  { key: "pv_power", color: "var(--gold)", kind: "area" as const, axis: "l" as const, unit: "W" },
  { key: "load_power", color: "var(--accent)", kind: "line" as const, axis: "l" as const, unit: "W" },
  { key: "battery_power", color: "var(--blue)", kind: "line" as const, axis: "l" as const, unit: "W" },
  { key: "grid_power", color: "var(--purple)", kind: "line" as const, axis: "l" as const, unit: "W" },
  { key: "battery_soc", color: "var(--green)", kind: "line" as const, axis: "r" as const, unit: "%", dashed: true },
];

function bucketFor(ms: number) {
  const h = ms / 3600_000;
  if (h <= 36) return "5m";
  if (h <= 24 * 8) return "15m";
  if (h <= 24 * 35) return "1h";
  return "1d";
}

export function History() {
  const { devices, selectedId, loading } = useDevices();
  if (loading) return <Skeleton className="h-96 w-full" />;
  if (!selectedId) return <NoDevices />;
  void devices;
  return <HistoryFor key={selectedId} id={selectedId} />;
}

function HistoryFor({ id }: { id: string }) {
  const t = useTranslations("history");
  const locale = useLocale() as Locale;
  const { me } = useMe();
  const [nowMs] = useState(() => Date.now());
  const [preset, setPreset] = useState<Preset>("today");
  const [from, setFrom] = useState(() => ymd(new Date(Date.now() - 6 * 864e5)));
  const [to, setTo] = useState(() => ymd(new Date()));
  const [on, setOn] = useState<string[]>(["pv_power", "load_power", "battery_soc"]);

  const [t0, t1] = useMemo(() => {
    const d0 = startOfDay().getTime();
    if (preset === "today") return [d0, d0 + 864e5];
    if (preset === "7d") return [d0 - 6 * 864e5, d0 + 864e5];
    if (preset === "30d") return [d0 - 29 * 864e5, d0 + 864e5];
    const a = new Date(from + "T00:00:00").getTime();
    const b = new Date(to + "T00:00:00").getTime() + 864e5;
    return Number.isFinite(a) && Number.isFinite(b) && b > a ? [a, b] : [d0, d0 + 864e5];
  }, [preset, from, to]);
  const bucket = bucketFor(t1 - t0);
  const metricsParam = on.join(",");

  const hist = useApi(on.length ? `hist:${id}:${t0}:${t1}:${metricsParam}` : null, () =>
    api.history(id, { from: new Date(t0).toISOString(), to: new Date(Math.min(t1, nowMs + 3600e3)).toISOString(), metrics: metricsParam, bucket }),
  );
  const days = Math.min(730, Math.max(1, Math.ceil((nowMs - t0) / 864e5)));
  const energy = useApi(`energy:${id}:${days}`, () => api.energy(id, days));

  const series: Series[] = METRICS.filter((m) => on.includes(m.key)).map((m) => ({
    key: m.key,
    label: t(`m_${m.key}`),
    color: m.color,
    kind: m.kind,
    axis: m.axis,
    dashed: m.dashed,
    unit: m.unit,
    data: (hist.data?.series?.[m.key] ?? []).map(([ts, v]) => [Date.parse(ts), v] as [number, number | null]),
  }));

  const energyRows = (energy.data ?? []).filter((e) => {
    const d = new Date(e.date + "T00:00:00").getTime();
    return d >= t0 - 1 && d < t1;
  });
  const fmtDay = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString(locale === "ar" ? "ar-SY-u-nu-latn" : "en-GB", { day: "numeric", month: "short" });
  const groups = energyRows.map((e) => ({
    label: fmtDay(e.date),
    values: [
      { key: "pv", v: e.pv_kwh, color: "var(--gold)", name: t("e_pv") },
      { key: "load", v: e.load_kwh, color: "var(--accent)", name: t("e_load") },
      { key: "grid", v: e.grid_kwh, color: "var(--purple)", name: t("e_grid") },
    ],
  }));
  const sum = (k: "pv_kwh" | "load_kwh" | "grid_kwh") => energyRows.reduce((a, e) => a + (e[k] ?? 0), 0);

  const exportPower = () => {
    const keys = series.map((s) => s.key);
    const ts = new Set<string>();
    for (const k of keys) for (const [x] of hist.data?.series?.[k] ?? []) ts.add(x);
    const maps = keys.map((k) => new Map(hist.data?.series?.[k] ?? []));
    const rows: (string | number | null)[][] = [["timestamp", ...keys]];
    [...ts].sort().forEach((x) => rows.push([x, ...maps.map((mp) => mp.get(x) ?? null)]));
    downloadCsv(`power_${ymd(new Date(t0))}_${ymd(new Date(t1 - 1))}.csv`, rows);
  };
  const exportEnergy = () => {
    const rows: (string | number | null)[][] = [["date", "pv_kwh", "load_kwh", "grid_kwh"]];
    energyRows.forEach((e) => rows.push([e.date, e.pv_kwh, e.load_kwh, e.grid_kwh]));
    downloadCsv(`energy_${ymd(new Date(t0))}_${ymd(new Date(t1 - 1))}.csv`, rows);
  };

  const toggle = (k: string) => setOn((x) => (x.includes(k) ? x.filter((y) => y !== k) : [...x, k]));
  const hasData = series.some((s) => s.data.length > 0);

  return (
    <div className="rise">
      <PageHeader eyebrow={t("eyebrow")} title={t("title")} actions={<DevicePicker />} />

      <Card className="mb-4">
        <div className="flex flex-wrap items-end gap-3">
          <Segmented<Preset>
            label={t("range")}
            value={preset}
            onChange={setPreset}
            className="w-full sm:w-auto sm:min-w-[420px]"
            options={[
              { value: "today", label: t("today") },
              { value: "7d", label: t("d7") },
              { value: "30d", label: t("d30") },
              { value: "custom", label: t("custom") },
            ]}
          />
          {preset === "custom" && (
            <div className="flex flex-wrap items-end gap-2">
              <Input label={t("from")} type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} dir="ltr" />
              <Input label={t("to")} type="date" value={to} min={from} max={ymd(new Date())} onChange={(e) => setTo(e.target.value)} dir="ltr" />
            </div>
          )}
        </div>
        <div className="mt-4 flex flex-wrap gap-2" role="group" aria-label={t("metrics")}>
          {METRICS.map((m) => {
            const active = on.includes(m.key);
            return (
              <button
                key={m.key}
                onClick={() => toggle(m.key)}
                aria-pressed={active}
                className={cx("inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-[13px] transition", active ? "border-accent bg-[color-mix(in_srgb,var(--accent)_12%,transparent)]" : "border-line text-muted hover:text-fg")}
              >
                <i className="h-2.5 w-2.5 rounded-[3px]" style={{ background: m.color, opacity: active ? 1 : 0.4 }} />
                {t(`m_${m.key}`)}
              </button>
            );
          })}
        </div>
      </Card>

      <Card className="mb-4">
        <CardTitle
          aside={
            <Button size="sm" variant="ghost" icon="download" onClick={exportPower} disabled={!hasData}>
              {t("export_power")}
            </Button>
          }
        >
          {t("power_chart")}
        </CardTitle>
        {hist.isLoading ? (
          <Skeleton className="h-[280px] w-full" />
        ) : hist.error ? (
          <ErrorState error={hist.error} onRetry={() => hist.mutate()} />
        ) : (
          <>
            <TimeChart series={series} t0={t0} t1={t1} height={280} emptyText={on.length ? t("no_data") : t("pick_metric")} />
            <Legend items={series.map((s) => ({ label: s.label, color: s.color }))} />
            <p className="mt-2 text-xs text-muted">{t("plan_note", { days: me.tenant.plan.history_days })}</p>
          </>
        )}
      </Card>

      <Card>
        <CardTitle
          aside={
            <Button size="sm" variant="ghost" icon="download" onClick={exportEnergy} disabled={!groups.length}>
              {t("export_energy")}
            </Button>
          }
        >
          {t("energy_chart")}
        </CardTitle>
        <div className="mb-3 grid grid-cols-3 gap-2 text-center">
          {[
            { k: t("e_pv"), v: sum("pv_kwh"), c: "var(--gold)" },
            { k: t("e_load"), v: sum("load_kwh"), c: "var(--accent)" },
            { k: t("e_grid"), v: sum("grid_kwh"), c: "var(--purple)" },
          ].map((x) => (
            <div key={x.k} className="rounded-xl border border-line px-2 py-2">
              <div className="text-xs text-muted">{x.k}</div>
              <div className="text-lg font-bold" style={{ color: x.c }}>
                <span dir="ltr" className="num">{fmt(x.v, 1)}</span> <small className="text-xs font-normal text-muted">kWh</small>
              </div>
            </div>
          ))}
        </div>
        {energy.isLoading ? (
          <Skeleton className="h-[240px] w-full" />
        ) : energy.error ? (
          <ErrorState error={energy.error} onRetry={() => energy.mutate()} />
        ) : (
          <>
            <BarChart groups={groups} emptyText={t("no_data")} />
            <Legend items={[{ label: t("e_pv"), color: "var(--gold)" }, { label: t("e_load"), color: "var(--accent)" }, { label: t("e_grid"), color: "var(--purple)" }]} />
          </>
        )}
      </Card>
    </div>
  );
}
