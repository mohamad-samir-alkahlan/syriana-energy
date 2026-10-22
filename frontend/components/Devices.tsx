"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { api, ApiError, type Device, type DiscoveredDevice, type DriverInfo, type Locale, type Site } from "@/lib/api";
import { canWrite, useApi, useDevices, useMe } from "@/lib/hooks";
import { relTime } from "@/lib/format";
import { addDemoDevice } from "@/lib/demo";
import { Icon } from "./Icon";
import { useToast } from "./Providers";
import { Badge, Button, Card, ConfirmModal, Dot, EmptyState, ErrorState, Input, Modal, PageHeader, Select, Skeleton, cx, errorText } from "./ui";

export function Devices() {
  const t = useTranslations("devices");
  const locale = useLocale() as Locale;
  const { me } = useMe();
  const toast = useToast();
  const sp = useSearchParams();
  const { sites, loading, error, reload } = useDevices();
  const writable = canWrite(me);
  const usage = useApi(`usage:${me.tenant.id}`, () => api.usage());
  const [wizard, setWizard] = useState(false);
  const [edit, setEdit] = useState<Device | null>(null);
  const [del, setDel] = useState<Device | null>(null);
  const [siteEdit, setSiteEdit] = useState<Site | null>(null);
  const [siteDel, setSiteDel] = useState<Site | null>(null);
  const [demoBusy, setDemoBusy] = useState(false);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (sp.get("add") === "1" && writable) setWizard(true);
  }, [sp, writable]);

  const demo = async () => {
    setDemoBusy(true);
    try {
      await addDemoDevice(t("demo_site"), t("demo_device"));
      await reload();
      toast(t("demo_added"));
    } catch (e) {
      toast(errorText(e, locale), "err");
    } finally {
      setDemoBusy(false);
    }
  };
  const total = sites.reduce((n, s) => n + s.devices.length, 0);

  return (
    <div className="rise">
      <PageHeader
        eyebrow={t("eyebrow")}
        title={t("title")}
        sub={usage.data ? t("usage", { n: usage.data.devices, max: usage.data.max_devices }) : undefined}
        actions={
          writable && (
            <>
              <Button variant="ghost" icon="play" onClick={demo} loading={demoBusy}>
                {t("try_demo")}
              </Button>
              <Button icon="plus" onClick={() => setWizard(true)}>
                {t("add")}
              </Button>
            </>
          )
        }
      />
      {loading && <Skeleton className="h-48 w-full" />}
      {error && <ErrorState error={error} onRetry={reload} />}
      {!loading && !error && total === 0 && sites.length === 0 && (
        <EmptyState
          icon="device"
          title={t("empty")}
          text={t("empty_text")}
          action={
            writable && (
              <>
                <Button icon="plus" onClick={() => setWizard(true)}>
                  {t("add")}
                </Button>
                <Button variant="ghost" icon="play" onClick={demo} loading={demoBusy}>
                  {t("try_demo")}
                </Button>
              </>
            )
          }
        />
      )}
      <div className="space-y-5">
        {sites.map((s) => (
          <section key={s.id}>
            <div className="mb-2 flex items-center justify-between gap-2">
              <h2 className="flex items-center gap-2 text-lg font-semibold">
                <Icon name="home" size={18} className="text-accent" />
                {s.name}
                <span className="text-xs font-normal text-muted">({s.devices.length})</span>
              </h2>
              {writable && (
                <div className="flex gap-1">
                  <Button size="sm" variant="ghost" onClick={() => setSiteEdit(s)} aria-label={t("rename_site")}>
                    <Icon name="edit" size={14} />
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setSiteDel(s)} aria-label={t("delete_site")}>
                    <Icon name="trash" size={14} />
                  </Button>
                </div>
              )}
            </div>
            {s.devices.length === 0 ? (
              <p className="rounded-xl border border-dashed border-line px-4 py-5 text-center text-sm text-muted">{t("site_empty")}</p>
            ) : (
              <div className="grid gap-3.5 md:grid-cols-2 xl:grid-cols-3">
                {s.devices.map((d) => (
                  <Card key={d.id}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <Dot on={d.online} />
                          <h3 className="truncate font-semibold">{d.name}</h3>
                        </div>
                        <p className="mt-0.5 text-xs text-muted">
                          {d.model || "—"} · <span dir="ltr" className="num">{d.serial || "—"}</span>
                        </p>
                      </div>
                      <Badge tone={d.online ? "green" : "red"}>{d.online ? t("online") : t("offline")}</Badge>
                    </div>
                    <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
                      <div>
                        <dt className="text-muted">{t("driver")}</dt>
                        <dd dir="ltr" className="num">{d.driver}</dd>
                      </div>
                      <div>
                        <dt className="text-muted">{t("last_seen")}</dt>
                        <dd>{d.last_seen ? relTime(d.last_seen, locale) : "—"}</dd>
                      </div>
                      <div>
                        <dt className="text-muted">{t("capacity")}</dt>
                        <dd dir="ltr" className="num">{d.battery_capacity_wh ? `${d.battery_capacity_wh} Wh` : "—"}</dd>
                      </div>
                    </dl>
                    {writable && (
                      <div className="mt-3 flex gap-2">
                        <Button size="sm" variant="ghost" icon="edit" onClick={() => setEdit(d)}>
                          {t("edit")}
                        </Button>
                        <Button size="sm" variant="danger" icon="trash" onClick={() => setDel(d)}>
                          {t("delete")}
                        </Button>
                      </div>
                    )}
                  </Card>
                ))}
              </div>
            )}
          </section>
        ))}
      </div>

      {wizard && (
        <Wizard
          sites={sites}
          onClose={() => setWizard(false)}
          onDone={async (n) => {
            setWizard(false);
            await reload();
            usage.mutate();
            toast(t("added", { n }));
          }}
        />
      )}
      {edit && (
        <EditDevice
          d={edit}
          onClose={() => setEdit(null)}
          onSaved={async () => {
            setEdit(null);
            await reload();
            toast(t("saved"));
          }}
        />
      )}
      {siteEdit && (
        <SiteName
          s={siteEdit}
          onClose={() => setSiteEdit(null)}
          onSaved={async () => {
            setSiteEdit(null);
            await reload();
          }}
        />
      )}
      <ConfirmModal
        open={!!del}
        danger
        title={t("delete_title")}
        text={t("delete_text", { name: del?.name ?? "" })}
        confirmLabel={t("delete")}
        onClose={() => setDel(null)}
        onConfirm={async () => {
          if (!del) return;
          try {
            await api.deleteDevice(del.id);
            await reload();
            usage.mutate();
          } catch (e) {
            toast(errorText(e, locale), "err");
          }
          setDel(null);
        }}
      />
      <ConfirmModal
        open={!!siteDel}
        danger
        title={t("delete_site_title")}
        text={t("delete_site_text", { name: siteDel?.name ?? "" })}
        confirmLabel={t("delete")}
        onClose={() => setSiteDel(null)}
        onConfirm={async () => {
          if (!siteDel) return;
          try {
            await api.deleteSite(siteDel.id);
            await reload();
            usage.mutate();
          } catch (e) {
            toast(errorText(e, locale), "err");
          }
          setSiteDel(null);
        }}
      />
    </div>
  );
}

function EditDevice({ d, onClose, onSaved }: { d: Device; onClose: () => void; onSaved: () => void }) {
  const t = useTranslations("devices");
  const locale = useLocale() as Locale;
  const [name, setName] = useState(d.name);
  const [cap, setCap] = useState(d.battery_capacity_wh ? String(d.battery_capacity_wh) : "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const save = async () => {
    setBusy(true);
    try {
      await api.updateDevice(d.id, { name: name.trim(), battery_capacity_wh: cap ? Number(cap) : null });
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
      onClose={onClose}
      title={t("edit_title")}
      footer={
        <>
          <Button variant="ghost" className="flex-1" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button className="flex-1" loading={busy} disabled={!name.trim() || (!!cap && !(Number(cap) > 0))} onClick={save}>
            {t("save")}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Input label={t("name")} value={name} onChange={(e) => setName(e.target.value)} data-autofocus />
        <Input label={t("capacity_label")} hint={t("capacity_hint")} type="number" min={0} step={100} dir="ltr" value={cap} onChange={(e) => setCap(e.target.value)} />
        {err && <p className="text-sm text-red">{err}</p>}
      </div>
    </Modal>
  );
}

function SiteName({ s, onClose, onSaved }: { s: Site; onClose: () => void; onSaved: () => void }) {
  const t = useTranslations("devices");
  const [name, setName] = useState(s.name);
  const [busy, setBusy] = useState(false);
  return (
    <Modal
      open
      onClose={onClose}
      title={t("rename_site")}
      footer={
        <>
          <Button variant="ghost" className="flex-1" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button
            className="flex-1"
            loading={busy}
            disabled={!name.trim()}
            onClick={async () => {
              setBusy(true);
              await api.updateSite(s.id, { name: name.trim() }).catch(() => {});
              onSaved();
            }}
          >
            {t("save")}
          </Button>
        </>
      }
    >
      <Input label={t("site_name")} value={name} onChange={(e) => setName(e.target.value)} data-autofocus />
    </Modal>
  );
}

/* ---------------- add device wizard ---------------- */
function Wizard({ sites, onClose, onDone }: { sites: Site[]; onClose: () => void; onDone: (n: number) => void }) {
  const t = useTranslations("devices");
  const locale = useLocale() as Locale;
  const drivers = useApi("drivers", () => api.drivers());
  const [step, setStep] = useState(1);
  const [driver, setDriver] = useState<DriverInfo | null>(null);
  const [creds, setCreds] = useState<Record<string, string>>({});
  const [token, setToken] = useState("");
  const [found, setFound] = useState<DiscoveredDevice[]>([]);
  const [picked, setPicked] = useState<Record<string, string>>({}); // external_id -> name
  const [siteId, setSiteId] = useState(sites[0]?.id ?? "__new");
  const [siteName, setSiteName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [limit, setLimit] = useState(false);

  const steps = [t("w_driver"), t("w_credentials"), t("w_pick"), t("w_site")];
  const dname = (d: DriverInfo) => (locale === "ar" ? d.name_ar || d.name : d.name);

  const discover = async () => {
    if (!driver) return;
    setBusy(true);
    setErr("");
    try {
      const r = await api.discover({ driver: driver.code, credentials: creds });
      setToken(r.integration_token);
      setFound(r.devices);
      setPicked(r.devices.length === 1 ? { [r.devices[0].external_id]: r.devices[0].name } : {});
      setStep(3);
    } catch (e) {
      setErr(errorText(e, locale));
    } finally {
      setBusy(false);
    }
  };
  const create = async () => {
    setBusy(true);
    setErr("");
    setLimit(false);
    try {
      let sid = siteId;
      if (sid === "__new") sid = (await api.createSite({ name: siteName.trim() })).id;
      const entries = Object.entries(picked);
      for (const [external_id, name] of entries) {
        await api.createDevice({ site_id: sid, driver: driver!.code, integration_token: token || undefined, external_id, name: name.trim() || external_id });
      }
      onDone(entries.length);
    } catch (e) {
      if (e instanceof ApiError && e.code === "plan_limit") setLimit(true);
      setErr(errorText(e, locale));
    } finally {
      setBusy(false);
    }
  };

  const credsOk = driver ? driver.credential_fields.every((f) => !f.required || creds[f.key]?.trim()) : false;
  const pickedN = Object.keys(picked).length;
  const siteOk = siteId !== "__new" || !!siteName.trim();

  return (
    <Modal open onClose={() => !busy && onClose()} title={t("wizard_title")} wide>
      <ol className="mb-5 flex gap-1.5" aria-label={t("steps")}>
        {steps.map((s, i) => (
          <li key={s} aria-current={step === i + 1 ? "step" : undefined} className="min-w-0 flex-1">
            <div className={cx("h-1 rounded-full", step > i ? "bg-accent" : "bg-line")} />
            <div className={cx("mt-1.5 truncate text-xs", step === i + 1 ? "text-fg" : "text-muted")}>
              {i + 1}. {s}
            </div>
          </li>
        ))}
      </ol>

      {step === 1 && (
        <div>
          {drivers.isLoading && <Skeleton className="h-24 w-full" />}
          {drivers.error && <ErrorState error={drivers.error} onRetry={() => drivers.mutate()} />}
          <div className="grid gap-2.5 sm:grid-cols-2">
            {(drivers.data ?? []).map((d) => (
              <button
                key={d.code}
                onClick={() => {
                  setDriver(d);
                  setCreds({});
                  setErr("");
                  setStep(2);
                }}
                className={cx("rounded-2xl border p-4 text-start transition hover:border-accent", driver?.code === d.code ? "border-accent bg-[color-mix(in_srgb,var(--accent)_10%,transparent)]" : "border-line")}
              >
                <div className="mb-1 flex items-center gap-2 font-medium">
                  <Icon name={d.code === "demo" ? "play" : "device"} size={18} className="text-accent" />
                  {dname(d)}
                </div>
                <div className="flex flex-wrap gap-1.5 text-xs text-muted">
                  <Badge>{d.kind}</Badge>
                  {d.supports_control && <Badge tone="blue">{t("control")}</Badge>}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {step === 2 && driver && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            discover();
          }}
          className="space-y-3"
        >
          <p className="text-sm text-muted">{driver.credential_fields.length ? t("creds_text", { name: dname(driver) }) : t("no_creds")}</p>
          {driver.credential_fields.map((f, i) => (
            <Input
              key={f.key}
              label={locale === "ar" ? f.label_ar || f.label : f.label}
              type={f.type === "password" ? "password" : "text"}
              dir="ltr"
              required={f.required}
              autoComplete="off"
              value={creds[f.key] ?? ""}
              onChange={(e) => setCreds({ ...creds, [f.key]: e.target.value })}
              data-autofocus={i === 0 ? true : undefined}
            />
          ))}
          {driver.credential_fields.length > 0 && <p className="flex items-center gap-1.5 text-xs text-muted"><Icon name="lock" size={13} />{t("creds_secure")}</p>}
          {err && <p role="alert" className="text-sm text-red">{err}</p>}
          <div className="flex gap-2 pt-1">
            <Button type="button" variant="ghost" className="flex-1" onClick={() => setStep(1)}>
              {t("back")}
            </Button>
            <Button type="submit" className="flex-1" loading={busy} disabled={!credsOk}>
              {t("discover")}
            </Button>
          </div>
        </form>
      )}

      {step === 3 && (
        <div>
          <p className="mb-3 text-sm text-muted">{found.length ? t("pick_text") : t("none_found")}</p>
          <div className="space-y-2">
            {found.map((d) => {
              const on = d.external_id in picked;
              return (
                <div key={d.external_id} className={cx("rounded-2xl border p-3", on ? "border-accent bg-[color-mix(in_srgb,var(--accent)_8%,transparent)]" : "border-line")}>
                  <label className="flex cursor-pointer items-center gap-3">
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={(e) => {
                        const n = { ...picked };
                        if (e.target.checked) n[d.external_id] = d.name;
                        else delete n[d.external_id];
                        setPicked(n);
                      }}
                      className="h-4 w-4 accent-[var(--accent)]"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="font-medium">{d.name}</div>
                      <div className="text-xs text-muted">
                        {d.model || "—"} · <span dir="ltr" className="num">{d.serial || d.external_id}</span>
                      </div>
                    </div>
                  </label>
                  {on && <Input className="mt-2" aria-label={t("name")} value={picked[d.external_id]} onChange={(e) => setPicked({ ...picked, [d.external_id]: e.target.value })} />}
                </div>
              );
            })}
          </div>
          <div className="mt-4 flex gap-2">
            <Button variant="ghost" className="flex-1" onClick={() => setStep(2)}>
              {t("back")}
            </Button>
            <Button className="flex-1" disabled={pickedN === 0} onClick={() => setStep(4)}>
              {t("next")}
            </Button>
          </div>
        </div>
      )}

      {step === 4 && (
        <div className="space-y-3">
          <Select label={t("site")} value={siteId} onChange={(e) => setSiteId(e.target.value)}>
            {sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
            <option value="__new">{t("new_site")}</option>
          </Select>
          {siteId === "__new" && <Input label={t("site_name")} placeholder={t("site_ph")} value={siteName} onChange={(e) => setSiteName(e.target.value)} data-autofocus />}
          <p className="text-sm text-muted">{t("will_add", { n: pickedN })}</p>
          {err && (
            <p role="alert" className="text-sm text-red">
              {err} {limit && <span className="text-muted">{t("limit_hint")}</span>}
            </p>
          )}
          <div className="flex gap-2 pt-1">
            <Button variant="ghost" className="flex-1" onClick={() => setStep(3)} disabled={busy}>
              {t("back")}
            </Button>
            <Button className="flex-1" loading={busy} disabled={!siteOk || pickedN === 0} onClick={create}>
              {t("finish")}
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}

