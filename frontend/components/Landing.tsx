"use client";

import { useState } from "react";
import { useTranslations, useLocale } from "next-intl";
import { Link } from "@/i18n/navigation";
import { api, type Feature, type Metrics, type Plan } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { fmt } from "@/lib/format";
import { FlowDiagram } from "./FlowDiagram";
import { Icon, type IconName } from "./Icon";
import { PoweredBy, PublicHeader } from "./Chrome";
import { Card, Eyebrow, ErrorState, Segmented, Skeleton, cx } from "./ui";

const DEMO: Metrics = {
  grid_available: false,
  grid_voltage: 0,
  pv_power: 1312,
  pv_voltage: 228.7,
  pv_current: 6,
  battery_soc: 70,
  battery_voltage: 26.9,
  battery_power: 650,
  load_power: 623,
  load_percent: 18,
  output_voltage: 230,
  bus_voltage: 379,
  inverter_temperature: 41,
  mode: "battery",
};

const FEATS: { icon: IconName; key: string }[] = [
  { icon: "flow", key: "live" },
  { icon: "bell", key: "alerts" },
  { icon: "sliders", key: "control" },
  { icon: "chat", key: "ai" },
  { icon: "bolt", key: "auto" },
  { icon: "key", key: "api" },
];

export function Landing({ loggedIn }: { loggedIn: boolean }) {
  const t = useTranslations("landing");
  return (
    <div>
      <PublicHeader
        right={
          loggedIn ? (
            <Link href="/app" className="rounded-xl bg-accent px-4 py-2 text-sm font-medium text-on-accent">
              {t("open_app")}
            </Link>
          ) : (
            <>
              <Link href="/login" className="hidden rounded-xl border border-line px-4 py-2 text-sm hover:border-accent sm:block">
                {t("login")}
              </Link>
              <Link href="/register" className="rounded-xl bg-accent px-4 py-2 text-sm font-medium text-on-accent">
                {t("register")}
              </Link>
            </>
          )
        }
      />

      <main className="mx-auto max-w-[1240px] px-4 sm:px-5">
        <section className="pb-6 pt-8 sm:pt-12">
          <Eyebrow>{t("eyebrow")}</Eyebrow>
          <h1 className="mt-1 max-w-3xl bg-gradient-to-r from-fg to-accent bg-clip-text text-[clamp(32px,6vw,60px)] font-bold leading-[1.15] tracking-tight text-transparent rtl:bg-gradient-to-l">
            {t("title")}
          </h1>
          <p className="mt-3 max-w-2xl text-base text-muted sm:text-lg">{t("sub")}</p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Link href={loggedIn ? "/app" : "/register"} className="inline-flex items-center gap-2 rounded-xl bg-accent px-6 py-3 font-medium text-on-accent hover:brightness-110">
              {loggedIn ? t("open_app") : t("cta")}
              <Icon name="arrowR" size={18} className="rtl:rotate-180" />
            </Link>
            <a href="#pricing" className="rounded-xl border border-line px-6 py-3 hover:border-accent">
              {t("see_pricing")}
            </a>
          </div>
          <div className="mt-8">
            <FlowDiagram metrics={DEMO} online model="24V" />
          </div>
        </section>

        <section className="py-10">
          <Eyebrow>{t("features_eyebrow")}</Eyebrow>
          <h2 className="mb-5 text-2xl font-bold sm:text-3xl">{t("features_title")}</h2>
          <div className="grid gap-3.5 sm:grid-cols-2 lg:grid-cols-3">
            {FEATS.map((f) => (
              <Card key={f.key} className="transition hover:border-accent">
                <div className="mb-3 grid h-11 w-11 place-items-center rounded-xl bg-[color-mix(in_srgb,var(--accent)_15%,transparent)] text-accent">
                  <Icon name={f.icon} size={22} />
                </div>
                <h3 className="font-semibold">{t(`f_${f.key}_t`)}</h3>
                <p className="mt-1 text-sm text-muted">{t(`f_${f.key}_d`)}</p>
              </Card>
            ))}
          </div>
        </section>

        <Pricing />

        <section className="my-12 rounded-[22px] border border-[color-mix(in_srgb,var(--accent)_35%,transparent)] bg-gradient-to-br from-[color-mix(in_srgb,var(--accent)_10%,transparent)] to-transparent p-7 text-center sm:p-12">
          <h2 className="text-2xl font-bold sm:text-3xl">{t("final_title")}</h2>
          <p className="mx-auto mt-2 max-w-lg text-muted">{t("final_sub")}</p>
          <Link href={loggedIn ? "/app" : "/register"} className="mt-5 inline-flex rounded-xl bg-accent px-7 py-3 font-medium text-on-accent hover:brightness-110">
            {loggedIn ? t("open_app") : t("cta")}
          </Link>
        </section>
      </main>
      <footer className="pb-10 pt-4">
        <PoweredBy />
      </footer>
    </div>
  );
}

function Pricing() {
  const t = useTranslations("landing");
  const f = useTranslations("features");
  const locale = useLocale();
  const [period, setPeriod] = useState<"month" | "year">("month");
  const { data, error, mutate } = useApi("plans", () => api.plans());
  const order = ["free", "home", "pro", "installer"];
  const plans = (data ?? []).slice().sort((a, b) => order.indexOf(a.code) - order.indexOf(b.code));
  return (
    <section id="pricing" className="scroll-mt-20 py-10">
      <Eyebrow>{t("pricing_eyebrow")}</Eyebrow>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <h2 className="text-2xl font-bold sm:text-3xl">{t("pricing_title")}</h2>
        <Segmented
          label={t("billing")}
          value={period}
          onChange={setPeriod}
          className="w-64"
          options={[
            { value: "month", label: t("monthly") },
            { value: "year", label: t("yearly") },
          ]}
        />
      </div>
      {error && <ErrorState error={error} onRetry={() => mutate()} />}
      {!data && !error && (
        <div className="grid gap-3.5 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-72" />
          ))}
        </div>
      )}
      <div className="grid gap-3.5 sm:grid-cols-2 lg:grid-cols-4">
        {plans.map((p) => (
          <PlanCard key={p.code} p={p} period={period} locale={locale} f={f} featured={p.code === "home"} />
        ))}
      </div>
    </section>
  );
}

export function PlanCard({
  p,
  period,
  locale,
  f,
  featured,
  current,
}: {
  p: Plan;
  period: "month" | "year";
  locale: string;
  f: (k: string) => string;
  featured?: boolean;
  current?: boolean;
}) {
  const t = useTranslations("landing");
  const price = period === "month" ? p.price_month : p.price_year;
  const all: Feature[] = ["control", "ai", "email", "webhook", "automations", "api", "white_label", "customers"];
  return (
    <div className={cx("flex flex-col rounded-[18px] border bg-panel p-5", featured || current ? "border-accent shadow-[0_0_0_1px_var(--accent)]" : "border-line")}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-lg font-semibold">{locale === "ar" ? p.name_ar || p.name : p.name}</h3>
        {current ? (
          <span className="rounded-full bg-accent px-2.5 py-0.5 text-xs text-on-accent">{t("current")}</span>
        ) : featured ? (
          <span className="rounded-full bg-accent px-2.5 py-0.5 text-xs text-on-accent">{t("popular")}</span>
        ) : null}
      </div>
      <div className="mt-3 flex items-baseline gap-1.5">
        <span dir="ltr" className="num text-4xl font-bold tracking-tight">
          {price === 0 ? t("free") : `$${fmt(price, price % 1 ? 2 : 0)}`}
        </span>
        {price > 0 && (
          <span className="text-sm text-muted">
            / {p.code === "installer" ? t("per_device") + " / " : ""}
            {period === "month" ? t("per_month") : t("per_year")}
          </span>
        )}
      </div>
      <ul className="mt-4 flex-1 space-y-2 text-sm">
        <li className="flex items-center gap-2">
          <Icon name="check" size={15} className="shrink-0 text-green" />
          {t("devices_n", { n: p.max_devices })}
        </li>
        <li className="flex items-center gap-2">
          <Icon name="check" size={15} className="shrink-0 text-green" />
          {t("history_n", { n: p.history_days })}
        </li>
        {all.map((k) => {
          const on = p.features.includes(k);
          return (
            <li key={k} className={cx("flex items-center gap-2", !on && "text-muted/60 line-through decoration-muted/30")}>
              <Icon name={on ? "check" : "x"} size={15} className={cx("shrink-0", on ? "text-green" : "text-muted/50")} />
              {f(k)}
            </li>
          );
        })}
      </ul>
      {!current && (
        <Link href="/register" className={cx("mt-5 rounded-xl border px-4 py-2.5 text-center text-sm font-medium transition", featured ? "border-accent bg-accent text-on-accent hover:brightness-110" : "border-line hover:border-accent")}>
          {t("choose")}
        </Link>
      )}
    </div>
  );
}
