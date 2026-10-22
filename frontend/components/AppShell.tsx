"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Link, usePathname, useRouter } from "@/i18n/navigation";
import { api, items, type Feature } from "@/lib/api";
import { DeviceProvider, resetCache, useApi, useMe } from "@/lib/hooks";
import { relTime } from "@/lib/format";
import { Icon, type IconName } from "./Icon";
import { BrandLogo, LangSwitch, PoweredBy, ThemeToggle, usePopover } from "./Chrome";
import { IconButton, cx } from "./ui";
import { useToast } from "./Providers";

interface NavItem {
  href: string;
  key: string;
  icon: IconName;
  feature?: Feature;
  admin?: boolean;
}
const NAV: NavItem[] = [
  { href: "/app", key: "dashboard", icon: "flow" },
  { href: "/app/history", key: "history", icon: "chart" },
  { href: "/app/control", key: "control", icon: "sliders", feature: "control" },
  { href: "/app/alerts", key: "alerts", icon: "bell" },
  { href: "/app/automations", key: "automations", icon: "bolt", feature: "automations" },
  { href: "/app/assistant", key: "assistant", icon: "chat", feature: "ai" },
  { href: "/app/devices", key: "devices", icon: "device" },
  { href: "/app/customers", key: "customers", icon: "users", feature: "customers" },
  { href: "/app/branding", key: "branding", icon: "palette", feature: "white_label" },
  { href: "/app/settings", key: "settings", icon: "gear" },
  { href: "/admin", key: "admin", icon: "admin", admin: true },
];
const MOBILE_MAIN = ["dashboard", "history", "control", "assistant"];

function isActive(path: string, href: string) {
  return href === "/app" ? path === "/app" : path === href || path.startsWith(href + "/");
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <DeviceProvider>
      <Shell>{children}</Shell>
    </DeviceProvider>
  );
}

function Shell({ children }: { children: ReactNode }) {
  const { me } = useMe();
  const t = useTranslations("nav");
  const path = usePathname();
  const nav = NAV.filter((n) => (n.admin ? me.user.is_superadmin : true));
  const [sheet, setSheet] = useState(false);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSheet(false);
  }, [path]);
  const feats = me.tenant.plan.features;

  return (
    <div className="min-h-dvh md:flex">
      {/* desktop sidebar */}
      <aside className="sticky top-0 hidden h-dvh w-[250px] shrink-0 flex-col gap-1 border-e border-line bg-[color-mix(in_srgb,var(--bg2)_85%,transparent)] p-4 md:flex">
        <Link href="/app" className="mb-4 block px-2 py-2">
          <BrandLogo />
        </Link>
        <nav className="flex flex-1 flex-col gap-0.5 overflow-y-auto" aria-label={t("main")}>
          {nav.map((n) => {
            const locked = n.feature && !feats.includes(n.feature);
            const a = isActive(path, n.href);
            return (
              <Link
                key={n.key}
                href={n.href}
                aria-current={a ? "page" : undefined}
                className={cx(
                  "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition",
                  a ? "bg-[color-mix(in_srgb,var(--accent)_16%,transparent)] font-medium text-fg" : "text-muted hover:bg-panel hover:text-fg",
                )}
              >
                <Icon name={n.icon} size={19} className={a ? "text-accent" : ""} />
                <span className="flex-1">{t(n.key)}</span>
                {locked && <Icon name="lock" size={13} />}
              </Link>
            );
          })}
        </nav>
        <PoweredBy className="pt-3" />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onMenu={() => setSheet(true)} />
        <main className="mx-auto w-full max-w-[1240px] flex-1 px-4 pb-28 pt-4 sm:px-5 md:pb-10">{children}</main>
      </div>

      {/* mobile bottom nav */}
      <nav
        aria-label={t("main")}
        className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-line bg-[color-mix(in_srgb,var(--bg2)_94%,transparent)] pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
      >
        {MOBILE_MAIN.map((k) => {
          const n = NAV.find((x) => x.key === k)!;
          const a = isActive(path, n.href);
          return (
            <Link key={k} href={n.href} aria-current={a ? "page" : undefined} className={cx("flex flex-col items-center gap-0.5 py-2 text-[11px]", a ? "text-accent" : "text-muted")}>
              <Icon name={n.icon} size={21} />
              {t(k)}
            </Link>
          );
        })}
        <button onClick={() => setSheet(true)} className="flex flex-col items-center gap-0.5 py-2 text-[11px] text-muted" aria-label={t("more")}>
          <Icon name="menu" size={21} />
          {t("more")}
        </button>
      </nav>

      {sheet && <MoreSheet nav={nav} onClose={() => setSheet(false)} path={path} />}
    </div>
  );
}

function MoreSheet({ nav, onClose, path }: { nav: NavItem[]; onClose: () => void; path: string }) {
  const t = useTranslations("nav");
  const c = useTranslations("common");
  const { me } = useMe();
  const router = useRouter();
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  }, [onClose]);
  const logout = async () => {
    await api.logout().catch(() => {});
    await resetCache();
    router.replace("/login");
  };
  return (
    <div className="fixed inset-0 z-50 bg-black/60 md:hidden" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-label={t("more")} className="pop absolute inset-x-0 bottom-0 max-h-[85dvh] overflow-auto rounded-t-3xl border-t border-line bg-surface p-4 pb-[calc(1rem+env(safe-area-inset-bottom))]">
        <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-line" />
        <div className="mb-3 px-1 text-sm text-muted">{me.user.name} · {me.user.email}</div>
        <div className="grid grid-cols-3 gap-2">
          {nav.map((n) => (
            <Link
              key={n.key}
              href={n.href}
              className={cx("flex flex-col items-center gap-1.5 rounded-2xl border p-3 text-center text-xs", isActive(path, n.href) ? "border-accent bg-[color-mix(in_srgb,var(--accent)_14%,transparent)]" : "border-line")}
            >
              <Icon name={n.icon} size={22} />
              {t(n.key)}
            </Link>
          ))}
        </div>
        <button onClick={logout} className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl border border-line py-2.5 text-sm text-muted">
          <Icon name="logout" size={17} /> {c("logout")}
        </button>
        <PoweredBy className="mt-3" />
      </div>
    </div>
  );
}

function TopBar({ onMenu }: { onMenu: () => void }) {
  const { me } = useMe();
  const router = useRouter();
  return (
    <header className="sticky top-0 z-30 flex items-center gap-2 border-b border-line bg-[color-mix(in_srgb,var(--bg)_88%,transparent)] px-4 py-3 backdrop-blur sm:px-5">
      <Link href="/app" className="min-w-0 md:hidden">
        <BrandLogo size={26} withName={false} />
      </Link>
      <TenantSwitcher />
      <div className="flex-1" />
      <div className="flex items-center gap-2">
        <AlertsBell />
        <LangSwitch persist />
        <ThemeToggle />
        <UserMenu name={me.user.name} onSettings={() => router.push("/app/settings")} onMenu={onMenu} />
      </div>
    </header>
  );
}

function UserMenu({ name, onSettings }: { name: string; onSettings: () => void; onMenu: () => void }) {
  const c = useTranslations("common");
  const n = useTranslations("nav");
  const { open, setOpen, ref } = usePopover();
  const router = useRouter();
  const logout = async () => {
    await api.logout().catch(() => {});
    await resetCache();
    router.replace("/login");
  };
  return (
    <div className="relative hidden md:block" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={name}
        className="grid h-[38px] w-[38px] place-items-center rounded-[10px] border border-line bg-panel text-sm font-semibold transition hover:border-accent"
      >
        {name.trim().slice(0, 1).toUpperCase()}
      </button>
      {open && (
        <div role="menu" className="pop absolute end-0 top-12 z-40 w-52 rounded-2xl border border-line bg-surface p-1.5 shadow-xl">
          <div className="truncate px-3 py-2 text-xs text-muted">{name}</div>
          <button role="menuitem" onClick={() => { setOpen(false); onSettings(); }} className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm hover:bg-panel-hi">
            <Icon name="gear" size={16} /> {n("settings")}
          </button>
          <button role="menuitem" onClick={logout} className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm text-red hover:bg-panel-hi">
            <Icon name="logout" size={16} /> {c("logout")}
          </button>
        </div>
      )}
    </div>
  );
}

function TenantSwitcher() {
  const { me, setMe } = useMe();
  const t = useTranslations("shell");
  const toast = useToast();
  const { open, setOpen, ref } = usePopover();
  const router = useRouter();
  if (me.tenants.length < 2) {
    return <span className="hidden max-w-[220px] truncate text-sm text-muted sm:block">{me.tenant.name}</span>;
  }
  const go = async (id: string) => {
    setOpen(false);
    if (id === me.tenant.id) return;
    try {
      setMe(await api.switchTenant(id));
      await resetCache();
      router.refresh();
    } catch {
      toast(t("switch_failed"), "err");
    }
  };
  return (
    <div className="relative min-w-0" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={t("switch_tenant")}
        className="flex max-w-[190px] items-center gap-2 rounded-full border border-line bg-panel px-3 py-1.5 text-sm transition hover:border-accent sm:max-w-[260px]"
      >
        <Icon name="users" size={15} className="shrink-0 text-accent" />
        <span className="truncate">{me.tenant.name}</span>
        <Icon name="chevD" size={14} className="shrink-0 text-muted" />
      </button>
      {open && (
        <ul role="listbox" className="pop absolute start-0 top-11 z-40 max-h-72 w-64 overflow-auto rounded-2xl border border-line bg-surface p-1.5 shadow-xl">
          {me.tenants.map((x) => (
            <li key={x.id} role="option" aria-selected={x.id === me.tenant.id}>
              <button onClick={() => go(x.id)} className={cx("flex w-full items-center justify-between gap-2 rounded-xl px-3 py-2 text-start text-sm hover:bg-panel-hi", x.id === me.tenant.id && "text-accent")}>
                <span className="truncate">{x.name}</span>
                {x.id === me.tenant.id && <Icon name="check" size={15} />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AlertsBell() {
  const t = useTranslations("shell");
  const locale = useLocale() as "ar" | "en";
  const { me } = useMe();
  const { open, setOpen, ref } = usePopover();
  const { data, mutate } = useApi(`bell:${me.tenant.id}`, () => api.alerts({ limit: 20 }), { refreshInterval: 30000 });
  const list = items(data);
  const unread = list.filter((a) => !a.read).length;
  return (
    <div className="relative" ref={ref}>
      <IconButton icon="bell" label={t("alerts")} badge={unread} onClick={() => setOpen(!open)} aria-expanded={open} />
      {open && (
        <div className="pop fixed inset-x-3 top-16 z-40 rounded-2xl border border-line bg-surface p-2 shadow-xl sm:absolute sm:inset-x-auto sm:end-0 sm:top-12 sm:w-80">
          <div className="flex items-center justify-between px-2 py-1.5 text-sm font-semibold">
            {t("alerts")}
            {unread > 0 && (
              <button
                className="text-xs font-normal text-accent"
                onClick={async () => {
                  await api.readAll().catch(() => {});
                  mutate();
                }}
              >
                {t("mark_all")}
              </button>
            )}
          </div>
          <div className="max-h-80 overflow-auto">
            {list.length === 0 && <p className="px-3 py-6 text-center text-sm text-muted">{t("no_alerts")}</p>}
            {list.slice(0, 6).map((a) => (
              <div key={a.id} className="flex gap-2.5 rounded-xl px-2 py-2 hover:bg-panel-hi">
                <span className={cx("mt-1.5 h-2 w-2 shrink-0 rounded-full", a.read ? "bg-transparent" : "bg-accent")} />
                <div className="min-w-0">
                  <div className="truncate text-sm">{locale === "ar" ? a.title_ar || a.title : a.title}</div>
                  <div className="text-xs text-muted">{relTime(a.created_at, locale)}</div>
                </div>
              </div>
            ))}
          </div>
          <Link href="/app/alerts" onClick={() => setOpen(false)} className="mt-1 block rounded-xl py-2 text-center text-sm text-accent hover:bg-panel-hi">
            {t("all_alerts")}
          </Link>
        </div>
      )}
    </div>
  );
}
