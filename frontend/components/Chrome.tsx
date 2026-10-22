"use client";

import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { usePathname, useRouter, Link } from "@/i18n/navigation";
import { useSearchParams } from "next/navigation";
import { api, type Locale } from "@/lib/api";
import { Icon, LogoMark } from "./Icon";
import { useBrandName, useBranding, useTheme } from "./Providers";
import { IconButton, cx } from "./ui";

export function BrandLogo({ size = 30, withName = true }: { size?: number; withName?: boolean }) {
  const b = useBranding();
  const name = useBrandName();
  return (
    <span className="inline-flex min-w-0 items-center gap-2.5 text-lg font-bold">
      {b.logo_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={b.logo_url} alt="" width={size} height={size} style={{ height: size, width: "auto", maxWidth: size * 3 }} className="rounded-md object-contain" />
      ) : (
        <LogoMark size={size} />
      )}
      {withName && <span className="truncate">{name}</span>}
    </span>
  );
}

export function LangSwitch({ persist }: { persist?: boolean }) {
  const locale = useLocale();
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const go = (l: Locale) => {
    if (l === locale) return;
    if (persist) api.updateMe({ locale: l }).catch(() => {});
    const q = sp.toString();
    router.replace(q ? `${pathname}?${q}` : pathname, { locale: l });
  };
  return (
    <div className="flex overflow-hidden rounded-[10px] border border-line" role="group" aria-label="Language">
      {(["ar", "en"] as const).map((l) => (
        <button
          key={l}
          onClick={() => go(l)}
          aria-pressed={l === locale}
          lang={l}
          className={cx("h-[38px] px-3 text-[13px] transition", l === locale ? "bg-accent text-on-accent" : "text-muted hover:text-fg")}
        >
          {l === "ar" ? "ع" : "EN"}
        </button>
      ))}
    </div>
  );
}

export function ThemeToggle() {
  const [theme, toggle] = useTheme();
  const t = useTranslations("common");
  return <IconButton icon={theme === "dark" ? "sun" : "moon"} label={theme === "dark" ? t("light_mode") : t("dark_mode")} onClick={toggle} />;
}

/** small hook: close a popover on outside click / Esc */
export function usePopover() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const key = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", down);
      document.removeEventListener("keydown", key);
    };
  }, [open]);
  return { open, setOpen, ref };
}

export function PublicHeader({ right }: { right?: React.ReactNode }) {
  return (
    <header className="mx-auto flex max-w-[1240px] items-center justify-between gap-3 px-4 py-4 sm:px-5">
      <Link href="/" aria-label="Home" className="min-w-0">
        <BrandLogo />
      </Link>
      <div className="flex items-center gap-2">
        <LangSwitch />
        <ThemeToggle />
        {right}
      </div>
    </header>
  );
}

export function PoweredBy({ className }: { className?: string }) {
  const b = useBranding();
  const t = useTranslations("common");
  if (!b.powered_by) return null;
  return (
    <div className={cx("flex items-center justify-center gap-1.5 text-xs text-muted", className)}>
      <Icon name="bolt" size={12} />
      {t("powered_by")}
    </div>
  );
}
