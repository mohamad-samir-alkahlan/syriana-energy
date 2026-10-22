"use client";

import { useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { api, ApiError, items, type Command, type Locale, type Setting } from "@/lib/api";
import { canWrite, useApi, useDevices, useMe } from "@/lib/hooks";
import { fmt, fmtDateTime } from "@/lib/format";
import { DevicePicker } from "./DevicePicker";
import { NoDevices } from "./NoDevices";
import { Icon } from "./Icon";
import { useToast } from "./Providers";
import { Badge, Button, Card, CardTitle, ErrorState, Modal, PageHeader, Segmented, Skeleton, Switch, Upsell, errorText } from "./ui";

export function Control() {
  const { selectedId, loading } = useDevices();
  if (loading) return <Skeleton className="h-96 w-full" />;
  if (!selectedId) return <NoDevices />;
  return <ControlFor key={selectedId} id={selectedId} />;
}

type Val = string | number | boolean | null;

function ControlFor({ id }: { id: string }) {
  const t = useTranslations("control");
  const locale = useLocale() as Locale;
  const { me } = useMe();
  const toast = useToast();
  const writable = canWrite(me);
  const settings = useApi(`settings:${id}`, () => api.settings(id));
  const commands = useApi(`commands:${id}`, () => api.commands(id));
  const [pending, setPending] = useState<{ s: Setting; next: Val } | null>(null);
  const [busy, setBusy] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, number>>({});

  const list = useMemo(() => settings.data ?? [], [settings.data]);
  const groups = useMemo(() => {
    const g = new Map<string, Setting[]>();
    for (const s of list) {
      const k = s.group || "";
      g.set(k, [...(g.get(k) ?? []), s]);
    }
    return [...g.entries()];
  }, [list]);

  const groupName = (g: string) => {
    const k = `group_${g.toLowerCase().replace(/[^a-z0-9]+/g, "_")}`;
    return t.has(k) ? t(k) : g;
  };
  const label = (s: Setting) => (locale === "ar" ? s.label_ar || s.label : s.label);
  const show = (s: Setting | undefined, v: unknown): string => {
    if (v === null || v === undefined) return "—";
    if (!s) return String(v);
    if (s.type === "enum") {
      const o = s.options?.find((x) => x.value === String(v));
      return o ? (locale === "ar" ? o.label_ar || o.label : o.label) : String(v);
    }
    if (s.type === "bool") return v ? t("on") : t("off");
    return `${typeof v === "number" ? fmt(v, v % 1 ? 1 : 0) : v}${s.unit ? " " + s.unit : ""}`;
  };

  if (settings.error instanceof ApiError && settings.error.code === "feature_not_in_plan") {
    return (
      <>
        <PageHeader eyebrow={t("eyebrow")} title={t("title")} />
        <Upsell feature="control" />
      </>
    );
  }

  const apply = async () => {
    if (!pending) return;
    setBusy(true);
    try {
      const cmd = await api.changeSetting(id, pending.s.key, pending.next);
      if (cmd.status === "failed") toast(t("failed_toast", { reason: cmd.error || "" }), "err");
      else toast(t("ok_toast"));
      setDrafts((d) => {
        const n = { ...d };
        delete n[pending.s.key];
        return n;
      });
      await Promise.all([settings.mutate(), commands.mutate()]);
    } catch (e) {
      toast(errorText(e, locale) || t("failed_toast", { reason: "" }), "err");
    } finally {
      setBusy(false);
      setPending(null);
    }
  };

  const cmds: Command[] = items(commands.data);

  return (
    <div className="rise">
      <PageHeader eyebrow={t("eyebrow")} title={t("title")} sub={t("sub")} actions={<DevicePicker />} />
      {!writable && <p className="mb-3 rounded-xl border border-line bg-panel px-4 py-2 text-sm text-muted">{t("viewer_note")}</p>}

      {settings.isLoading && <Skeleton className="h-80 w-full" />}
      {settings.error && !(settings.error instanceof ApiError && settings.error.code === "feature_not_in_plan") && <ErrorState error={settings.error} onRetry={() => settings.mutate()} />}

      <div className="grid gap-4 lg:grid-cols-2">
        {groups.map(([g, ss]) => (
          <Card key={g} className="lg:[&:only-child]:col-span-2">
            {g && <CardTitle>{groupName(g)}</CardTitle>}
            {ss.map((s) => (
              <div key={s.key} className="border-b border-line py-3.5 first:pt-0 last:border-0 last:pb-0">
                {s.type === "bool" ? (
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm">
                      {label(s)}
                      <div className="text-xs text-muted">{t("current")}: {show(s, s.value)}</div>
                    </div>
                    <Switch checked={!!s.value} label={label(s)} disabled={!writable} onChange={(v) => setPending({ s, next: v })} />
                  </div>
                ) : (
                  <>
                    <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-3 text-sm">
                      <span>{label(s)}</span>
                      <span className="text-xs text-muted">
                        {t("current")}: <span dir="ltr" className="num">{show(s, s.value)}</span>
                      </span>
                    </div>
                    {s.type === "enum" && (
                      <Segmented
                        label={label(s)}
                        value={String(s.value ?? "")}
                        options={(s.options ?? []).map((o) => ({ value: o.value, label: locale === "ar" ? o.label_ar || o.label : o.label }))}
                        onChange={(v) => writable && v !== String(s.value) && setPending({ s, next: v })}
                      />
                    )}
                    {s.type === "number" && <NumberControl s={s} draft={drafts[s.key]} writable={writable} onDraft={(n) => setDrafts((d) => ({ ...d, [s.key]: n }))} onApply={(n) => setPending({ s, next: n })} />}
                  </>
                )}
              </div>
            ))}
          </Card>
        ))}
      </div>

      <Card className="mt-4">
        <CardTitle aside={t("log_sub")}>{t("log")}</CardTitle>
        {commands.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : commands.error && !(commands.error instanceof ApiError && commands.error.code === "feature_not_in_plan") ? (
          <ErrorState error={commands.error} onRetry={() => commands.mutate()} />
        ) : cmds.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted">{t("no_commands")}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-sm">
              <thead>
                <tr className="text-start text-xs text-muted">
                  <th className="pb-2 text-start font-normal">{t("col_time")}</th>
                  <th className="pb-2 text-start font-normal">{t("col_setting")}</th>
                  <th className="pb-2 text-start font-normal">{t("col_change")}</th>
                  <th className="pb-2 text-start font-normal">{t("col_user")}</th>
                  <th className="pb-2 text-start font-normal">{t("col_status")}</th>
                </tr>
              </thead>
              <tbody>
                {cmds.slice(0, 30).map((c) => {
                  const s = list.find((x) => x.key === c.key);
                  return (
                    <tr key={c.id} className="border-t border-line align-top">
                      <td className="py-2.5 pe-3 text-muted whitespace-nowrap">{fmtDateTime(c.created_at, locale)}</td>
                      <td className="py-2.5 pe-3">{s ? label(s) : c.key}</td>
                      <td className="py-2.5 pe-3">
                        <span className="text-muted line-through">{show(s, c.old_value)}</span>
                        <Icon name="arrow" size={13} className="mx-1.5 inline text-accent ltr:rotate-180" />
                        <b className="font-medium">{show(s, c.new_value)}</b>
                      </td>
                      <td className="py-2.5 pe-3">{c.user_name || "—"}</td>
                      <td className="py-2.5">
                        <Badge tone={c.status === "ok" ? "green" : c.status === "failed" ? "red" : "gold"}>{t(`st_${c.status}`)}</Badge>
                        {c.error && <div className="mt-0.5 text-xs text-red">{c.error}</div>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Modal
        open={!!pending}
        onClose={() => !busy && setPending(null)}
        title={t("confirm_title")}
        footer={
          <>
            <Button variant="ghost" className="flex-1" onClick={() => setPending(null)} disabled={busy}>
              {t("cancel")}
            </Button>
            <Button className="flex-1" onClick={apply} loading={busy}>
              {t("confirm_send")}
            </Button>
          </>
        }
      >
        {pending && (
          <>
            <p className="text-sm text-muted">{label(pending.s)}</p>
            <div className="my-3.5 flex flex-wrap items-center gap-2.5 rounded-xl border border-line bg-panel p-3 text-sm">
              <span className="text-muted line-through">{show(pending.s, pending.s.value)}</span>
              <Icon name="arrow" size={20} className="text-accent ltr:rotate-180" />
              <span className="font-semibold text-[color-mix(in_srgb,var(--accent)_55%,var(--text))]">{show(pending.s, pending.next)}</span>
            </div>
            <div className="flex items-start gap-1.5 text-xs text-gold">
              <Icon name="info" size={14} className="mt-0.5 shrink-0" />
              {t("confirm_hint")}
            </div>
          </>
        )}
      </Modal>
    </div>
  );
}

function NumberControl({ s, draft, writable, onDraft, onApply }: { s: Setting; draft?: number; writable: boolean; onDraft: (n: number) => void; onApply: (n: number) => void }) {
  const t = useTranslations("control");
  const min = s.min ?? 0;
  const max = s.max ?? 100;
  const step = s.step ?? 1;
  const cur = typeof s.value === "number" ? s.value : min;
  const val = draft ?? cur;
  const changed = draft !== undefined && draft !== cur;
  const bad = val < min || val > max || Number.isNaN(val);
  return (
    <div>
      <div className="flex items-center gap-3">
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={Number.isNaN(val) ? min : Math.min(max, Math.max(min, val))}
          disabled={!writable}
          aria-label={s.label}
          onChange={(e) => onDraft(Number(e.target.value))}
          className="w-full"
          dir="ltr"
        />
        <div dir="ltr" className="flex shrink-0 items-center gap-1">
          <input
            type="number"
            min={min}
            max={max}
            step={step}
            value={Number.isNaN(val) ? "" : val}
            disabled={!writable}
            onChange={(e) => onDraft(e.target.value === "" ? NaN : Number(e.target.value))}
            aria-label={s.label}
            dir="ltr"
            className="w-20 rounded-[10px] border border-line bg-bg2 px-2 py-1.5 text-center text-sm focus:border-accent focus:outline-none"
          />
          {s.unit && <span className="text-xs text-muted">{s.unit}</span>}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-start gap-1.5 text-xs text-gold">
          <Icon name="info" size={14} className="mt-0.5 shrink-0" />
          {t("safe_range", { min: fmt(min, min % 1 ? 1 : 0), max: fmt(max, max % 1 ? 1 : 0), unit: s.unit || "" })}
        </div>
        {changed && (
          <Button size="sm" disabled={bad} onClick={() => onApply(val)}>
            {t("apply")}
          </Button>
        )}
      </div>
      {changed && bad && <p className="mt-1 text-xs text-red">{t("out_of_range")}</p>}
    </div>
  );
}
