"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { api, ApiError, items, type AutoAction, type AutoCondition, type AutoOp, type Automation, type AutomationInput, type Locale } from "@/lib/api";
import { canWrite, useApi, useDevices, useMe } from "@/lib/hooks";
import { relTime } from "@/lib/format";
import { Icon } from "./Icon";
import { useToast } from "./Providers";
import { Badge, Button, Card, ConfirmModal, EmptyState, ErrorState, Input, Modal, PageHeader, Segmented, Select, Skeleton, Switch, Upsell, cx, errorText } from "./ui";

const METRICS = ["battery_soc", "battery_voltage", "pv_power", "load_power", "load_percent", "battery_power", "grid_voltage", "inverter_temperature"];
const OPS: AutoOp[] = ["<", "<=", ">", ">=", "=="];
const UNIT: Record<string, string> = { battery_soc: "%", battery_voltage: "V", pv_power: "W", load_power: "W", load_percent: "%", battery_power: "W", grid_voltage: "V", inverter_temperature: "°C" };

const blank = (): AutomationInput => ({ name: "", enabled: true, device_id: null, conditions: [{ metric: "battery_soc", op: "<", value: 30 }], grid: "any", actions: [{ type: "notify", message: "" }], recover_conditions: [], recover_actions: [] });

export function Automations() {
  const t = useTranslations("auto");
  const locale = useLocale() as Locale;
  const { me } = useMe();
  const toast = useToast();
  const writable = canWrite(me);
  const { data, error, isLoading, mutate } = useApi(`autos:${me.tenant.id}`, () => api.automations());
  const [editing, setEditing] = useState<{ id: string | null; draft: AutomationInput } | null>(null);
  const [del, setDel] = useState<Automation | null>(null);
  const list = items(data);

  if (error instanceof ApiError && error.code === "feature_not_in_plan")
    return (
      <>
        <PageHeader eyebrow={t("eyebrow")} title={t("title")} />
        <Upsell feature="automations" />
      </>
    );

  const toggle = async (a: Automation, v: boolean) => {
    try {
      await api.updateAutomation(a.id, { enabled: v });
      await mutate();
    } catch (e) {
      toast(errorText(e, locale), "err");
    }
  };

  return (
    <div className="rise">
      <PageHeader
        eyebrow={t("eyebrow")}
        title={t("title")}
        sub={t("sub")}
        actions={
          writable && (
            <Button icon="plus" onClick={() => setEditing({ id: null, draft: blank() })}>
              {t("new")}
            </Button>
          )
        }
      />
      {isLoading && <Skeleton className="h-64 w-full" />}
      {error && <ErrorState error={error} onRetry={() => mutate()} />}
      {!isLoading && !error && list.length === 0 && (
        <EmptyState
          icon="bolt"
          title={t("empty")}
          text={t("empty_text")}
          action={
            writable && (
              <>
                <Button icon="plus" onClick={() => setEditing({ id: null, draft: blank() })}>
                  {t("new")}
                </Button>
                <Button variant="ghost" onClick={() => setEditing({ id: null, draft: template(t) })}>
                  {t("use_template")}
                </Button>
              </>
            )
          }
        />
      )}
      <div className="space-y-4">
        {list.map((a) => (
          <Card key={a.id}>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-base font-semibold">{a.name}</h3>
                <Badge tone={a.state === "active" ? "gold" : "muted"}>{t(`state_${a.state}`)}</Badge>
                {a.last_triggered_at && <span className="text-xs text-muted">{t("last", { when: relTime(a.last_triggered_at, locale) })}</span>}
              </div>
              <div className="flex items-center gap-2">
                <Switch checked={a.enabled} label={t("enabled")} disabled={!writable} onChange={(v) => toggle(a, v)} />
                {writable && (
                  <>
                    <Button size="sm" variant="ghost" icon="edit" onClick={() => setEditing({ id: a.id, draft: { name: a.name, enabled: a.enabled, device_id: a.device_id, conditions: a.conditions, grid: a.grid, actions: a.actions, recover_conditions: a.recover_conditions, recover_actions: a.recover_actions } })}>
                        {t("edit")}
                    </Button>
                    <Button size="sm" variant="danger" aria-label={t("delete")} onClick={() => setDel(a)}>
                      <Icon name="trash" size={15} />
                    </Button>
                  </>
                )}
              </div>
            </div>
            <RuleDiagram a={a} active={a.state === "active" && a.enabled} />
          </Card>
        ))}
      </div>

      {editing && (
        <Builder
          key={editing.id ?? "new"}
          initial={editing.draft}
          editingId={editing.id}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null);
            await mutate();
          }}
        />
      )}
      <ConfirmModal
        open={!!del}
        danger
        title={t("delete_title")}
        text={del?.name}
        confirmLabel={t("delete")}
        onClose={() => setDel(null)}
        onConfirm={async () => {
          if (!del) return;
          try {
            await api.deleteAutomation(del.id);
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

function template(t: (k: string) => string): AutomationInput {
  return {
    name: t("tpl_name"),
    enabled: true,
    device_id: null,
    conditions: [{ metric: "battery_soc", op: "<", value: 30 }],
    grid: "lost",
    actions: [
      { type: "notify", message: t("tpl_notify") },
      { type: "http", method: "POST", url: "http://192.168.1.50/relay/0?turn=off", body: "" },
    ],
    recover_conditions: [{ metric: "battery_soc", op: ">", value: 60 }],
    recover_actions: [
      { type: "http", method: "POST", url: "http://192.168.1.50/relay/0?turn=on", body: "" },
      { type: "notify", message: t("tpl_recover") },
    ],
  };
}

/* ---------- visual summary (like the mockup's rule diagram) ---------- */
export function useCondText() {
  const t = useTranslations("auto");
  return {
    cond: (c: AutoCondition) => `${(METRICS.includes(c.metric) ? t(`m_${c.metric}`) : c.metric)} ${c.op} ${c.value}${UNIT[c.metric] ?? ""}`,
    action: (a: AutoAction) => (a.type === "notify" ? t("a_notify_s", { m: a.message || "—" }) : a.type === "http" ? t("a_http_s", { method: a.method, url: a.url.replace(/^https?:\/\//, "").slice(0, 34) }) : t("a_setting_s", { key: a.key, value: String(a.value) })),
    grid: (g: string) => (g === "any" ? null : t(`grid_${g}`)),
  };
}

function Box({ tone, title, lines, empty }: { tone: string; title: string; lines: string[]; empty?: string }) {
  return (
    <div className="min-w-0 rounded-2xl border bg-node p-3.5" style={{ borderColor: tone }}>
      <div className="mb-1.5 text-center text-[15px] font-medium">{title}</div>
      <div className="space-y-0.5 text-center text-[13px] text-muted">
        {lines.length ? lines.map((l, i) => <div key={i} className="break-words">{l}</div>) : <div>{empty}</div>}
      </div>
    </div>
  );
}
function Arrow({ color, slow }: { color: string; slow?: boolean }) {
  return (
    <svg viewBox="0 0 64 44" className="mx-auto h-9 w-14 rotate-90 md:rotate-0 md:rtl:-scale-x-100" aria-hidden="true">
      <defs>
        <marker id={`ar${color.replace(/\W/g, "")}`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0 0 L10 5 L0 10 z" fill={color} />
        </marker>
      </defs>
      <path className={cx("flow", slow && "slow")} stroke={color} markerEnd={`url(#ar${color.replace(/\W/g, "")})`} d="M2 22 C 20 6, 38 38, 58 22" />
    </svg>
  );
}
export function RuleDiagram({ a, active }: { a: Pick<Automation, "conditions" | "grid" | "actions" | "recover_conditions" | "recover_actions">; active?: boolean }) {
  const t = useTranslations("auto");
  const x = useCondText();
  const ifLines = [...a.conditions.map(x.cond), ...(x.grid(a.grid) ? [x.grid(a.grid)!] : [])];
  const recLines = [...a.recover_conditions.map(x.cond), ...a.recover_actions.map(x.action)];
  return (
    <div className={cx("grid items-center gap-1 md:grid-cols-[1fr_auto_1fr_auto_1fr]", active && "drop-shadow-[0_0_14px_color-mix(in_srgb,var(--accent)_30%,transparent)]")}>
      <Box tone="var(--green)" title={t("if")} lines={ifLines.length ? ifLines : []} empty={t("always")} />
      <Arrow color="var(--accent)" />
      <Box tone="var(--accent)" title={t("do")} lines={a.actions.map(x.action)} empty="—" />
      <Arrow color="var(--blue)" slow />
      <Box tone="var(--blue)" title={t("recover")} lines={recLines} empty={t("no_recover")} />
    </div>
  );
}

/* ---------- builder ---------- */
function Builder({ initial, editingId, onClose, onSaved }: { initial: AutomationInput; editingId: string | null; onClose: () => void; onSaved: () => void }) {
  const t = useTranslations("auto");
  const locale = useLocale() as Locale;
  const toast = useToast();
  const { devices } = useDevices();
  const [d, setD] = useState<AutomationInput>(initial);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const devId = d.device_id || devices[0]?.id || null;
  const settings = useApi(devId ? `settings:${devId}` : null, () => api.settings(devId!), { shouldRetryOnError: false });

  const valid =
    d.name.trim() &&
    d.actions.length > 0 &&
    d.conditions.every((c) => Number.isFinite(c.value)) &&
    d.recover_conditions.every((c) => Number.isFinite(c.value)) &&
    [...d.actions, ...d.recover_actions].every((a) => (a.type === "http" ? /^https?:\/\//.test(a.url) : a.type === "setting" ? !!a.key : true));

  const save = async () => {
    setBusy(true);
    setErr("");
    try {
      if (editingId) await api.updateAutomation(editingId, d);
      else await api.createAutomation(d);
      toast(t("saved"));
      onSaved();
    } catch (e) {
      setErr(errorText(e, locale));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      wide
      onClose={() => !busy && onClose()}
      title={editingId ? t("edit_title") : t("new_title")}
      footer={
        <>
          <Button variant="ghost" className="flex-1" onClick={onClose} disabled={busy}>
            {t("cancel")}
          </Button>
          <Button className="flex-1" onClick={save} loading={busy} disabled={!valid}>
            {t("save")}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        <div className="grid gap-3 sm:grid-cols-2">
          <Input label={t("name")} value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} placeholder={t("name_ph")} data-autofocus />
          <Select label={t("device")} value={d.device_id ?? ""} onChange={(e) => setD({ ...d, device_id: e.target.value || null })}>
            <option value="">{t("device_any")}</option>
            {devices.map((x) => (
              <option key={x.id} value={x.id}>
                {x.name}
              </option>
            ))}
          </Select>
        </div>

        <Section title={t("if")} color="var(--green)">
          <CondEditor list={d.conditions} onChange={(c) => setD({ ...d, conditions: c })} />
          <div className="mt-3">
            <div className="mb-1.5 text-[13px] text-muted">{t("grid_label")}</div>
            <Segmented
              value={d.grid}
              onChange={(g) => setD({ ...d, grid: g })}
              options={[
                { value: "any", label: t("grid_any") },
                { value: "available", label: t("grid_available") },
                { value: "lost", label: t("grid_lost") },
              ]}
            />
          </div>
        </Section>

        <Section title={t("do")} color="var(--accent)">
          <ActionEditor list={d.actions} onChange={(a) => setD({ ...d, actions: a })} settingKeys={(settings.data ?? []).map((s) => ({ key: s.key, label: locale === "ar" ? s.label_ar || s.label : s.label }))} />
        </Section>

        <Section title={t("recover")} color="var(--blue)" hint={t("recover_hint")}>
          <div className="mb-1 text-[13px] text-muted">{t("recover_conditions")}</div>
          <CondEditor list={d.recover_conditions} onChange={(c) => setD({ ...d, recover_conditions: c })} />
          <div className="mb-1 mt-4 text-[13px] text-muted">{t("recover_actions")}</div>
          <ActionEditor list={d.recover_actions} onChange={(a) => setD({ ...d, recover_actions: a })} settingKeys={(settings.data ?? []).map((s) => ({ key: s.key, label: locale === "ar" ? s.label_ar || s.label : s.label }))} />
        </Section>

        <div>
          <div className="mb-2 text-[13px] text-muted">{t("preview")}</div>
          <RuleDiagram a={d} />
        </div>
        {err && (
          <p role="alert" className="text-sm text-red">
            {err}
          </p>
        )}
      </div>
    </Modal>
  );
}

function Section({ title, color, hint, children }: { title: string; color: string; hint?: string; children: React.ReactNode }) {
  return (
    <fieldset className="rounded-2xl border p-3.5" style={{ borderColor: `color-mix(in srgb, ${color} 55%, transparent)` }}>
      <legend className="px-2 text-sm font-semibold" style={{ color }}>
        {title}
      </legend>
      {hint && <p className="mb-2 text-xs text-muted">{hint}</p>}
      {children}
    </fieldset>
  );
}

function CondEditor({ list, onChange }: { list: AutoCondition[]; onChange: (l: AutoCondition[]) => void }) {
  const t = useTranslations("auto");
  const set = (i: number, p: Partial<AutoCondition>) => onChange(list.map((c, j) => (j === i ? { ...c, ...p } : c)));
  return (
    <div className="space-y-2">
      {list.map((c, i) => (
        <div key={i} className="flex flex-wrap items-center gap-2">
          <Select aria-label={t("metric")} value={c.metric} onChange={(e) => set(i, { metric: e.target.value })} className="min-w-0 flex-1 basis-40 !py-2">
            {METRICS.map((m) => (
              <option key={m} value={m}>
                {t(`m_${m}`)}
              </option>
            ))}
          </Select>
          <Select aria-label={t("op")} value={c.op} onChange={(e) => set(i, { op: e.target.value as AutoOp })} className="!w-20 !py-2" dir="ltr">
            {OPS.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </Select>
          <div className="flex w-28 items-center gap-1.5">
            <Input aria-label={t("value")} type="number" dir="ltr" value={Number.isFinite(c.value) ? c.value : ""} onChange={(e) => set(i, { value: e.target.value === "" ? NaN : Number(e.target.value) })} className="!py-2" />
            <span className="text-xs text-muted">{UNIT[c.metric]}</span>
          </div>
          <button type="button" aria-label={t("remove")} onClick={() => onChange(list.filter((_, j) => j !== i))} className="grid h-9 w-9 place-items-center rounded-lg text-muted hover:text-red">
            <Icon name="x" size={16} />
          </button>
        </div>
      ))}
      <Button size="sm" variant="ghost" icon="plus" onClick={() => onChange([...list, { metric: "battery_soc", op: "<", value: 30 }])}>
        {t("add_condition")}
      </Button>
    </div>
  );
}

function ActionEditor({ list, onChange, settingKeys }: { list: AutoAction[]; onChange: (l: AutoAction[]) => void; settingKeys: { key: string; label: string }[] }) {
  const t = useTranslations("auto");
  const set = (i: number, a: AutoAction) => onChange(list.map((x, j) => (j === i ? a : x)));
  const retype = (i: number, type: AutoAction["type"]) =>
    set(i, type === "notify" ? { type, message: "" } : type === "http" ? { type, method: "POST", url: "", body: "" } : { type, key: settingKeys[0]?.key ?? "", value: "" });
  return (
    <div className="space-y-3">
      {list.map((a, i) => (
        <div key={i} className="rounded-xl border border-line p-3">
          <div className="mb-2 flex items-center gap-2">
            <Select aria-label={t("action_type")} value={a.type} onChange={(e) => retype(i, e.target.value as AutoAction["type"])} className="!py-2">
              <option value="notify">{t("a_notify")}</option>
              <option value="http">{t("a_http")}</option>
              <option value="setting">{t("a_setting")}</option>
            </Select>
            <button type="button" aria-label={t("remove")} onClick={() => onChange(list.filter((_, j) => j !== i))} className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-muted hover:text-red">
              <Icon name="x" size={16} />
            </button>
          </div>
          {a.type === "notify" && <Input aria-label={t("message")} placeholder={t("message")} value={a.message} onChange={(e) => set(i, { ...a, message: e.target.value })} />}
          {a.type === "http" && (
            <div className="space-y-2">
              <div className="flex gap-2">
                <Select aria-label="method" value={a.method} onChange={(e) => set(i, { ...a, method: e.target.value })} className="!w-28 !py-2" dir="ltr">
                  {["GET", "POST", "PUT"].map((m) => (
                    <option key={m}>{m}</option>
                  ))}
                </Select>
                <Input aria-label="URL" placeholder="http://192.168.1.50/relay/0?turn=off" dir="ltr" value={a.url} onChange={(e) => set(i, { ...a, url: e.target.value })} />
              </div>
              {a.method !== "GET" && <Input aria-label={t("body")} placeholder={t("body")} dir="ltr" value={a.body ?? ""} onChange={(e) => set(i, { ...a, body: e.target.value })} />}
              <p className="text-xs text-muted">{t("http_hint")}</p>
            </div>
          )}
          {a.type === "setting" && (
            <div className="flex gap-2">
              {settingKeys.length ? (
                <Select aria-label={t("setting_key")} value={a.key} onChange={(e) => set(i, { ...a, key: e.target.value })} className="!py-2">
                  {settingKeys.map((s) => (
                    <option key={s.key} value={s.key}>
                      {s.label}
                    </option>
                  ))}
                </Select>
              ) : (
                <Input aria-label={t("setting_key")} placeholder="output_priority" dir="ltr" value={a.key} onChange={(e) => set(i, { ...a, key: e.target.value })} />
              )}
              <Input
                aria-label={t("value")}
                placeholder={t("value")}
                dir="ltr"
                className="!w-32"
                value={String(a.value)}
                onChange={(e) => {
                  const v = e.target.value;
                  set(i, { ...a, value: v === "true" ? true : v === "false" ? false : v !== "" && !Number.isNaN(Number(v)) ? Number(v) : v });
                }}
              />
            </div>
          )}
        </div>
      ))}
      <Button size="sm" variant="ghost" icon="plus" onClick={() => onChange([...list, { type: "notify", message: "" }])}>
        {t("add_action")}
      </Button>
    </div>
  );
}
