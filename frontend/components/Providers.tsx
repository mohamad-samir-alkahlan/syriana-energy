"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useLocale } from "next-intl";
import type { Branding } from "@/lib/api";

/* ---------------- branding ---------------- */
const BrandingCtx = createContext<Branding | null>(null);
export function BrandingProvider({ branding, children }: { branding: Branding; children: ReactNode }) {
  return <BrandingCtx.Provider value={branding}>{children}</BrandingCtx.Provider>;
}
export function useBranding(): Branding {
  const b = useContext(BrandingCtx);
  if (!b) throw new Error("BrandingProvider missing");
  return b;
}
export function useBrandName() {
  const b = useBranding();
  const locale = useLocale();
  return locale === "ar" ? b.name_ar || b.name : b.name || b.name_ar;
}

/* ---------------- toasts ---------------- */
type ToastKind = "ok" | "err" | "info";
interface ToastItem {
  id: number;
  kind: ToastKind;
  text: string;
}
const ToastCtx = createContext<(text: string, kind?: ToastKind) => void>(() => {});
export function useToast() {
  return useContext(ToastCtx);
}
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const seq = useRef(0);
  const push = useCallback((text: string, kind: ToastKind = "ok") => {
    const id = ++seq.current;
    setItems((x) => [...x.slice(-3), { id, kind, text }]);
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), kind === "err" ? 6000 : 3200);
  }, []);
  const color = { ok: "var(--green)", err: "var(--red)", info: "var(--blue)" } as const;
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div
        aria-live="polite"
        role="status"
        className="pointer-events-none fixed inset-x-0 bottom-20 z-[70] flex flex-col items-center gap-2 px-4 md:bottom-6"
      >
        {items.map((t) => (
          <div
            key={t.id}
            className="pop pointer-events-auto max-w-md rounded-xl border bg-surface px-4 py-2.5 text-sm shadow-lg"
            style={{ borderColor: color[t.kind], color: color[t.kind] }}
          >
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

/* ---------------- theme ---------------- */
export type Theme = "dark" | "light";
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>("dark");
  useEffect(() => {
    const t = document.documentElement.getAttribute("data-theme");
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTheme(t === "light" ? "light" : "dark");
  }, []);
  const toggle = useCallback(() => {
    const next: Theme = document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem("se_theme", next);
    } catch {}
    setTheme(next);
  }, []);
  return [theme, toggle];
}

