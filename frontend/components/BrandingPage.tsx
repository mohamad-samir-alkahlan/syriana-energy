"use client";

import { useEffect, useState, type CSSProperties } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import { api, type Locale } from "@/lib/api";
import { canWrite, useHasFeature, useMe } from "@/lib/hooks";
import { onColor, safeColor } from "@/lib/color";
import { Icon, LogoMark } from "./Icon";
import { FlowDiagram } from "./FlowDiagram";
import { useToast } from "./Providers";
import { Button, Card, CardTitle, Input, PageHeader, Upsell, errorText } from "./ui";

export function BrandingPage() {
  const has = useHasFeature("white_label");
  const t = useTranslations("brand");
  if (!has)
    return (
      <>
        <PageHeader eyebrow={t("eyebrow")} title={t("title")} />
        <Upsell feature="white_label" />
      </>
    );
  return <Editor />;
}

function ColorField({ label, value, onChange, disabled }: { label: string; value: string; onChange: (v: string) => void; disabled?: boolean }) {
  const valid = /^#[0-9a-f]{6}$/i.test(value);
  return (
    <div>
      <div className="mb-1.5 text-[13px] text-muted">{label}</div>
      <div className="flex items-center gap-2">
        <input type="color" aria-label={label} disabled={disabled} value={valid ? value : "#da7756"} onChange={(e) => onChange(e.target.value)} className="h-[42px] w-14 cursor-pointer rounded-[10px] border border-line bg-transparent p-1" />
        <Input aria-label={label} dir="ltr" disabled={disabled} value={value} onChange={(e) => onChange(e.target.value)} error={valid ? undefined : " "} className="font-mono" />
      </div>
    </div>
  );
}

function Editor() {
  const t = useTranslations("brand");
  const locale = useLocale() as Locale;
  const { me, setMe } = useMe();
  const toast = useToast();
  const router = useRouter();
  const writable = canWrite(me);
  const b = me.tenant.branding;
  const [f, setF] = useState({
    name: b.name,
    name_ar: b.name_ar,
    logo_url: b.logo_url ?? "",
    primary_color: b.primary_color,
    accent_color: b.accent_color,
    support_email: b.support_email ?? "",
    custom_domain: me.tenant.custom_domain ?? "",
  });
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (v: string) => setF({ ...f, [k]: v });
  const colorsOk = /^#[0-9a-f]{6}$/i.test(f.primary_color) && /^#[0-9a-f]{6}$/i.test(f.accent_color);
  const domainOk = !f.custom_domain || /^([a-z0-9-]+\.)+[a-z]{2,}$/i.test(f.custom_domain);

  const save = async () => {
    setBusy(true);
    try {
      await api.updateBranding({ ...f, logo_url: f.logo_url.trim() || null, support_email: f.support_email.trim() || null, custom_domain: f.custom_domain.trim().toLowerCase() || null });
      setMe(await api.me());
      toast(t("saved"));
      router.refresh();
    } catch (e) {
      toast(errorText(e, locale), "err");
    } finally {
      setBusy(false);
    }
  };

  const primary = safeColor(f.primary_color, "#DA7756");
  const accent2 = safeColor(f.accent_color, "#d9b86b");
  const pvStyle = { "--accent": primary, "--accent2": accent2, "--on-accent": onColor(primary) } as CSSProperties;
  const name = locale === "ar" ? f.name_ar || f.name : f.name || f.name_ar;
  const [host, setHost] = useState("energy.example.com");
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setHost(window.location.host);
  }, []);

  return (
    <div className="rise">
      <PageHeader eyebrow={t("eyebrow")} title={t("title")} sub={t("sub")} />
      <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <Card>
          <CardTitle>{t("identity")}</CardTitle>
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <Input label={t("name_en")} value={f.name} disabled={!writable} onChange={(e) => set("name")(e.target.value)} dir="ltr" />
              <Input label={t("name_ar")} value={f.name_ar} disabled={!writable} onChange={(e) => set("name_ar")(e.target.value)} />
            </div>
            <Input label={t("logo")} hint={t("logo_hint")} type="url" dir="ltr" placeholder="https://…/logo.png" value={f.logo_url} disabled={!writable} onChange={(e) => set("logo_url")(e.target.value)} />
            <div className="grid gap-3 sm:grid-cols-2">
              <ColorField label={t("primary")} value={f.primary_color} onChange={set("primary_color")} disabled={!writable} />
              <ColorField label={t("accent")} value={f.accent_color} onChange={set("accent_color")} disabled={!writable} />
            </div>
            <Input label={t("support")} type="email" dir="ltr" value={f.support_email} disabled={!writable} onChange={(e) => set("support_email")(e.target.value)} />
            <Input label={t("domain")} placeholder="energy.yourcompany.com" dir="ltr" value={f.custom_domain} disabled={!writable} onChange={(e) => set("custom_domain")(e.target.value)} error={domainOk ? undefined : t("domain_bad")} />
            {writable && (
              <Button onClick={save} loading={busy} disabled={!colorsOk || !domainOk || !f.name.trim()}>
                {t("save")}
              </Button>
            )}
          </div>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardTitle aside={t("preview_hint")}>{t("preview")}</CardTitle>
            <div style={pvStyle} className="overflow-hidden rounded-2xl border border-line bg-bg">
              <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
                <span className="inline-flex min-w-0 items-center gap-2.5 text-base font-bold">
                  {f.logo_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={f.logo_url} alt="" style={{ height: 26, width: "auto", maxWidth: 90 }} className="object-contain" />
                  ) : (
                    <LogoMark size={26} />
                  )}
                  <span className="truncate">{name}</span>
                </span>
                <span className="rounded-lg bg-accent px-3 py-1.5 text-xs text-on-accent">{t("pv_button")}</span>
              </div>
              <div className="p-3">
                <div className="mb-2 inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs" style={{ color: accent2, borderColor: `color-mix(in srgb, ${accent2} 40%, transparent)`, background: `color-mix(in srgb, ${accent2} 12%, transparent)` }}>
                  <Icon name="battery" size={12} /> {t("pv_chip")}
                </div>
                <FlowDiagram online model="24V" metrics={{ grid_available: false, pv_power: 1312, load_power: 623, battery_soc: 70, battery_power: 650, battery_voltage: 26.9, pv_voltage: 228.7, mode: "battery" }} />
              </div>
              <div className="px-4 pb-3 text-center text-xs text-muted">{t("pv_footer")}</div>
            </div>
          </Card>

          <Card>
            <CardTitle>{t("domain_title")}</CardTitle>
            <ol className="list-decimal space-y-2 ps-5 text-sm text-muted marker:text-accent">
              <li>{t("dns_1", { domain: f.custom_domain || "energy.yourcompany.com" })}</li>
              <li>
                {t("dns_2")}
                <code dir="ltr" className="mt-1.5 block rounded-lg border border-line bg-bg2 px-3 py-2 text-start text-xs text-fg">
                  {(f.custom_domain || "energy.yourcompany.com") + "  CNAME  " + host}
                </code>
              </li>
              <li>{t("dns_3")}</li>
            </ol>
          </Card>
        </div>
      </div>
    </div>
  );
}
