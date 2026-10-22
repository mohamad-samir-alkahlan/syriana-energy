"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { api, items, type Alert, type AlertRule, type AlertType, type Channel, type Locale } from "@/lib/api";
import { canWrite, useApi, useMe } from "@/lib/hooks";
import { relTime, fmtDateTime } from "@/lib/format";
import { alertIcon } from "./Dashboard";
import { Icon } from "./Icon";
import { useToast } from "./Providers";
import { Badge, Button, Card, EmptyState, ErrorState, Input, PageHeader, Skeleton, Switch, Tabs, cx, errorText } from "./ui";

const TYPES: AlertType[] = ["battery_low", "battery_full", "grid_lost", "grid_restored", "overload", "fault", "device_offline", "high_temperature", "daily_summary"];
const DEFAULTS: Record<AlertType, Record<string, number>> = {
  battery_low: { threshold_soc: 30 },
  battery_full: { threshold_soc: 100 },
  grid_lost: {},
  grid_restored: {},
  overload: { threshold_percent: 90, minutes: 3 },
  fault: {},
  device_offline: { minutes: 10 },
  high_temperature: { threshold_c: 60 },
  daily_summary: { hour_local: 21 },
};
const PARAM_META: Record<string, { min: number; max: number }> = {
  threshold_soc: { min: 1, max: 100 },
  threshold_percent: { min: 10, max: 100 },
  minutes: { min: 1, max: 1440 },
  threshold_c: { min: 30, max: 120 },
  hour_local: { min: 0, max: 23 },
};
const CHANNELS: { key: Channel; feature?: "email" | "webhook" }[] = [{ key: "telegram" }, { key: "email", feature: "email" }, { key: "webhook", feature: "webhook" }, { key: "inapp" }];

export function Alerts() {
  const t = useTranslations("alerts");
  const [tab, setTab] = useState<"list" | "rules">("list");
  return (
    <div className="rise">
      <PageHeader eyebrow={t("eyebrow")} title={t("title")} />
      <Tabs
        value={tab}
        onChange={setTab}
        options={[
          { value: "list", label: t("tab_list"), icon: "bell" },
          { value: "rules", label: t("tab_rules"), icon: "sliders" },
        ]}
      />
      {tab === "list" ? <AlertList /> : <Rules />}
    </div>
  );
}

function AlertList() {
  const t = useTranslations("alerts");
  const locale = useLocale() as Locale;
  const { me } = useMe();
  const toast = useToast();
  const [unreadOnly, setUnreadOnly] = useState(false);
  const { data, error, isLoading, mutate } = useApi(`alerts:all:${me.tenant.id}`, () => api.alerts({ limit: 100 }), { refreshInterval: 30000 });
  const list = items(data);
  const shown = unreadOnly ? list.filter((a) => !a.read) : list;
  const unread = list.filter((a) => !a.read).length;

  const markAll = async () => {
    try {
      await api.readAll();
      await mutate();
    } catch (e) {
      toast(errorText(e, locale), "err");
    }
  };
  const markOne = async (a: Alert) => {
    if (a.read) return;
    try {
      await api.readAlert(a.id);
      await mutate();
    } catch (e) {
      toast(errorText(e, locale), "err");
    }
  };

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm">
          <Switch checked={unreadOnly} onChange={setUnreadOnly} label={t("unread_only")} />
          {t("unread_only")}
          {unread > 0 && <Badge tone="accent">{unread}</Badge>}
        </div>
        <Button variant="ghost" size="sm" icon="check" onClick={markAll} disabled={unread === 0}>
          {t("mark_all")}
        </Button>
      </div>
      {isLoading && (
        <div className="space-y-2">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-16" />
          ))}
        </div>
      )}
      {error && <ErrorState error={error} onRetry={() => mutate()} />}
      {!isLoading && !error && shown.length === 0 && <EmptyState icon="bell" title={t("empty")} text={t("empty_text")} />}
      <div className="space-y-2">
        {shown.map((a) => {
          const s = alertIcon(a);
          return (
            <Card key={a.id} className={cx("flex items-start gap-3 !p-3.5", !a.read && "border-[color-mix(in_srgb,var(--accent)_45%,transparent)]")}>
              <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl" style={{ background: `color-mix(in srgb, ${s.c} 14%, transparent)`, color: s.c }}>
                <Icon name={s.icon} size={19} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-2">
                  <b className="text-[15px]">{locale === "ar" ? a.title_ar || a.title : a.title}</b>
                  {!a.read && <span className="h-2 w-2 rounded-full bg-accent" aria-label={t("unread")} />}
                </div>
                {(locale === "ar" ? a.body_ar || a.body : a.body) && <p className="text-sm text-muted">{locale === "ar" ? a.body_ar || a.body : a.body}</p>}
                <p className="mt-0.5 text-xs text-muted">
                  {a.device_name ? `${a.device_name} · ` : ""}
                  <span title={fmtDateTime(a.created_at, locale)}>{relTime(a.created_at, locale)}</span>
                </p>
              </div>
              {!a.read && (
                <Button size="sm" variant="ghost" onClick={() => markOne(a)} aria-label={t("mark_read")}>
                  <Icon name="check" size={15} />
                  <span className="hidden sm:inline">{t("mark_read")}</span>
                </Button>
              )}
            </Card>
          );
        })}
      </div>
    </>
  );
}

function Rules() {
  const t = useTranslations("alerts");
  const { me } = useMe();
  const rules = useApi(`rules:${me.tenant.id}`, () => api.alertRules());
  const writable = canWrite(me);
  const list = items(rules.data);
  const missing = TYPES.filter((ty) => !list.some((r) => r.type === ty));
  const toast = useToast();
  const locale = useLocale() as Locale;

  const add = async (type: AlertType) => {
    try {
      await api.createAlertRule({ type, enabled: true, params: DEFAULTS[type], channels: ["inapp"], cooldown_minutes: 30 });
      await rules.mutate();
    } catch (e) {
      toast(errorText(e, locale), "err");
    }
  };
  return (
    <>
      <p className="mb-3 text-sm text-muted">{t("rules_sub")}</p>
      {rules.isLoading && <Skeleton className="h-64 w-full" />}
      {rules.error && <ErrorState error={rules.error} onRetry={() => rules.mutate()} />}
      <div className="grid gap-3.5 lg:grid-cols-2">
        {TYPES.map((ty) => list.filter((r) => r.type === ty).map((r) => <RuleCard key={r.id} rule={r} writable={writable} onSaved={() => rules.mutate()} />))}
      </div>
      {missing.length > 0 && writable && !rules.isLoading && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <span className="text-sm text-muted">{t("add_rule")}:</span>
          {missing.map((ty) => (
            <Button key={ty} size="sm" variant="ghost" icon="plus" onClick={() => add(ty)}>
              {t(`type_${ty}`)}
            </Button>
          ))}
        </div>
      )}
    </>
  );
}

function RuleCard({ rule, writable, onSaved }: { rule: AlertRule; writable: boolean; onSaved: () => void }) {
  const t = useTranslations("alerts");
  const locale = useLocale() as Locale;
  const { me } = useMe();
  const toast = useToast();
  const [r, setR] = useState(rule);
  const [busy, setBusy] = useState(false);
  const dirty = JSON.stringify(r) !== JSON.stringify(rule);
  const feats = me.tenant.plan.features;

  const save = async (next: AlertRule = r) => {
    setBusy(true);
    try {
      await api.updateAlertRule(rule.id, { enabled: next.enabled, params: next.params, channels: next.channels, cooldown_minutes: next.cooldown_minutes });
      toast(t("saved"));
      onSaved();
    } catch (e) {
      toast(errorText(e, locale), "err");
      setR(rule);
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    setBusy(true);
    try {
      await api.deleteAlertRule(rule.id);
      onSaved();
    } catch (e) {
      toast(errorText(e, locale), "err");
    } finally {
      setBusy(false);
    }
  };
  const toggleCh = (c: Channel) => setR({ ...r, channels: r.channels.includes(c) ? r.channels.filter((x) => x !== c) : [...r.channels, c] });
  const paramKeys = Object.keys(DEFAULTS[r.type] ?? {});

  return (
    <Card className={cx(!r.enabled && "opacity-75")}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold">{t(`type_${r.type}`)}</h3>
          <p className="text-xs text-muted">{t(`desc_${r.type}`)}</p>
        </div>
        <Switch
          checked={r.enabled}
          disabled={!writable || busy}
          label={t("enabled")}
          onChange={(v) => {
            const n = { ...r, enabled: v };
            setR(n);
            if (!dirty) save(n);
          }}
        />
      </div>

      {paramKeys.length > 0 && (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {paramKeys.map((k) => (
            <Input
              key={k}
              label={t(`p_${k}`)}
              type="number"
              dir="ltr"
              disabled={!writable}
              min={PARAM_META[k]?.min}
              max={PARAM_META[k]?.max}
              value={r.params[k] ?? ""}
              onChange={(e) => setR({ ...r, params: { ...r.params, [k]: e.target.value === "" ? NaN : Number(e.target.value) } })}
            />
          ))}
        </div>
      )}

      <div className="mt-3">
        <div className="mb-1.5 text-[13px] text-muted">{t("channels")}</div>
        <div className="flex flex-wrap gap-1.5">
          {CHANNELS.map((c) => {
            const locked = c.feature && !feats.includes(c.feature);
            const on = r.channels.includes(c.key);
            return (
              <button
                key={c.key}
                type="button"
                disabled={!writable || !!locked}
                aria-pressed={on}
                title={locked ? t("locked") : undefined}
                onClick={() => toggleCh(c.key)}
                className={cx(
                  "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition disabled:cursor-not-allowed disabled:opacity-50",
                  on ? "border-[color-mix(in_srgb,var(--green)_55%,transparent)] text-green" : "border-line text-muted",
                )}
              >
                {on && <Icon name="check" size={12} />}
                {locked && <Icon name="lock" size={12} />}
                {t(`ch_${c.key}`)}
              </button>
            );
          })}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-end justify-between gap-3">
        <Input label={t("cooldown")} type="number" dir="ltr" min={0} max={10080} className="!w-32" disabled={!writable} value={Number.isNaN(r.cooldown_minutes) ? "" : r.cooldown_minutes} onChange={(e) => setR({ ...r, cooldown_minutes: e.target.value === "" ? NaN : Number(e.target.value) })} />
        <div className="flex gap-2">
          {writable && (
            <Button size="sm" variant="danger" onClick={remove} disabled={busy} aria-label={t("delete_rule")}>
              <Icon name="trash" size={15} />
            </Button>
          )}
          {dirty && (
            <Button size="sm" onClick={() => save()} loading={busy} disabled={[...paramKeys.map((k) => r.params[k]), r.cooldown_minutes].some((v) => typeof v === "number" && Number.isNaN(v))}>
              {t("save")}
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
}
