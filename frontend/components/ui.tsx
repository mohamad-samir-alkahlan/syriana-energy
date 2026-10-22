"use client";

import {
  useEffect,
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { createPortal } from "react-dom";
import { useLocale, useTranslations } from "next-intl";
import { ApiError } from "@/lib/api";
import { Link } from "@/i18n/navigation";
import { Icon, type IconName } from "./Icon";

export function cx(...a: (string | false | null | undefined)[]) {
  return a.filter(Boolean).join(" ");
}

/* ---------- Card / headings ---------- */
export function Card({ className, children, ...rest }: { className?: string; children: ReactNode } & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cx("rounded-[18px] border border-line bg-panel p-4 sm:p-[18px]", className)} {...rest}>
      {children}
    </div>
  );
}
export function CardTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <h3 className="mb-3 flex flex-wrap items-center justify-between gap-2 text-base font-semibold">
      <span>{children}</span>
      {aside && <span className="text-xs font-normal text-muted">{aside}</span>}
    </h3>
  );
}
export function Eyebrow({ children }: { children: ReactNode }) {
  return <div className="text-xs font-semibold uppercase tracking-[.12em] text-accent">{children}</div>;
}
export function PageHeader({ eyebrow, title, sub, actions }: { eyebrow?: ReactNode; title: ReactNode; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        {eyebrow && <Eyebrow>{eyebrow}</Eyebrow>}
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{title}</h1>
        {sub && <p className="mt-1 text-sm text-muted">{sub}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/* ---------- Button ---------- */
type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "danger" | "soft";
  size?: "sm" | "md";
  icon?: IconName;
  loading?: boolean;
};
export function Button({ variant = "primary", size = "md", icon, loading, className, children, disabled, ...rest }: BtnProps) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-xl border font-medium transition disabled:cursor-not-allowed disabled:opacity-50 select-none";
  const sz = size === "sm" ? "px-3 py-1.5 text-[13px]" : "px-4 py-2.5 text-sm";
  const v = {
    primary: "border-accent bg-accent text-on-accent hover:brightness-110",
    soft: "border-[color-mix(in_srgb,var(--accent)_45%,transparent)] bg-[color-mix(in_srgb,var(--accent)_14%,transparent)] hover:bg-[color-mix(in_srgb,var(--accent)_22%,transparent)]",
    ghost: "border-line bg-transparent hover:border-accent hover:bg-panel",
    danger: "border-red/60 bg-transparent text-red hover:bg-[color-mix(in_srgb,var(--red)_12%,transparent)]",
  }[variant];
  return (
    <button className={cx(base, sz, v, className)} disabled={disabled || loading} {...rest}>
      {loading ? <Spinner /> : icon ? <Icon name={icon} size={size === "sm" ? 15 : 17} /> : null}
      {children}
    </button>
  );
}
export function IconButton({ icon, label, className, badge, ...rest }: { icon: IconName; label: string; badge?: number } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      aria-label={label}
      title={label}
      className={cx("relative grid h-[38px] w-[38px] place-items-center rounded-[10px] border border-line bg-panel transition hover:border-accent", className)}
      {...rest}
    >
      <Icon name={icon} />
      {!!badge && (
        <span className="absolute -start-1 -top-1 min-w-[18px] rounded-full bg-accent px-1 text-center text-[10px] leading-[18px] text-on-accent">
          {badge > 99 ? "99+" : badge}
        </span>
      )}
    </button>
  );
}
export function Spinner({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className="animate-spin" aria-hidden="true">
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="3" opacity=".25" />
      <path d="M21 12a9 9 0 0 0-9-9" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

/* ---------- inputs ---------- */
const inputCls =
  "w-full rounded-[10px] border border-line bg-bg2 px-3 py-2.5 text-sm placeholder:text-muted/70 focus:border-accent focus:outline-none disabled:opacity-50";
export function Field({ label, hint, error, children, htmlFor }: { label: ReactNode; hint?: ReactNode; error?: ReactNode; children: ReactNode; htmlFor?: string }) {
  return (
    <div className="block">
      <label htmlFor={htmlFor} className="mb-1.5 block text-[13px] text-muted">
        {label}
      </label>
      {children}
      {hint && !error && <p className="mt-1 text-xs text-muted">{hint}</p>}
      {error && <p className="mt-1 text-xs text-red">{error}</p>}
    </div>
  );
}
export function Input({ label, hint, error, className, id, ...rest }: { label?: ReactNode; hint?: ReactNode; error?: ReactNode } & InputHTMLAttributes<HTMLInputElement>) {
  const auto = useId();
  const iid = id || auto;
  const el = <input id={iid} className={cx(inputCls, className)} {...rest} />;
  return label ? (
    <Field label={label} hint={hint} error={error} htmlFor={iid}>
      {el}
    </Field>
  ) : (
    el
  );
}
export function Select({ label, className, id, children, ...rest }: { label?: ReactNode } & SelectHTMLAttributes<HTMLSelectElement>) {
  const auto = useId();
  const iid = id || auto;
  const el = (
    <select id={iid} className={cx(inputCls, "appearance-none bg-no-repeat pe-8", className)} {...rest}>
      {children}
    </select>
  );
  return label ? (
    <Field label={label} htmlFor={iid}>
      {el}
    </Field>
  ) : (
    el
  );
}
export function Textarea({ label, className, id, ...rest }: { label?: ReactNode } & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const auto = useId();
  const iid = id || auto;
  const el = <textarea id={iid} className={cx(inputCls, "min-h-[80px]", className)} {...rest} />;
  return label ? (
    <Field label={label} htmlFor={iid}>
      {el}
    </Field>
  ) : (
    el
  );
}

export function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cx(
        "relative h-[26px] w-[46px] shrink-0 rounded-full transition disabled:opacity-50",
        checked ? "bg-accent" : "bg-[color-mix(in_srgb,var(--muted)_35%,transparent)]",
      )}
    >
      <span
        className={cx(
          "absolute top-[3px] h-5 w-5 rounded-full bg-white shadow transition-all",
          checked ? "start-[23px]" : "start-[3px]",
        )}
      />
    </button>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
  className,
}: {
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (v: T) => void;
  label?: string;
  className?: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className={cx("flex flex-wrap gap-1.5", className)}>
      {options.map((o) => {
        const cur = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={cur}
            onClick={() => onChange(o.value)}
            className={cx(
              "min-w-[90px] flex-1 rounded-[10px] border px-2.5 py-2 text-[13px] transition",
              cur
                ? "border-accent bg-[color-mix(in_srgb,var(--accent)_16%,transparent)] font-medium"
                : "border-line hover:border-accent",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function Tabs<T extends string>({ value, options, onChange }: { value: T; options: { value: T; label: ReactNode; icon?: IconName }[]; onChange: (v: T) => void }) {
  return (
    <div role="tablist" className="-mx-1 mb-5 flex gap-1 overflow-x-auto px-1 pb-1">
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={o.value === value}
          onClick={() => onChange(o.value)}
          className={cx(
            "flex shrink-0 items-center gap-2 rounded-full border px-4 py-2 text-sm transition",
            o.value === value ? "border-accent bg-[color-mix(in_srgb,var(--accent)_16%,transparent)] font-medium" : "border-line text-muted hover:text-fg",
          )}
        >
          {o.icon && <Icon name={o.icon} size={16} />}
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Badge({ children, tone = "muted" }: { children: ReactNode; tone?: "muted" | "green" | "red" | "gold" | "blue" | "accent" }) {
  const c = { muted: "var(--muted)", green: "var(--green)", red: "var(--red)", gold: "var(--gold)", blue: "var(--blue)", accent: "var(--accent)" }[tone];
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs"
      style={{ color: c, borderColor: `color-mix(in srgb, ${c} 45%, transparent)`, background: `color-mix(in srgb, ${c} 10%, transparent)` }}
    >
      {children}
    </span>
  );
}

export function Dot({ on, pulse = true }: { on: boolean; pulse?: boolean }) {
  const c = on ? "var(--green)" : "var(--red)";
  return (
    <span
      className="inline-block h-2 w-2 shrink-0 rounded-full"
      style={{ background: c, boxShadow: `0 0 10px ${c}`, animation: on && pulse ? "pulse 2s infinite" : undefined }}
    />
  );
}

/* ---------- states ---------- */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton", className)} aria-hidden="true" />;
}
export function EmptyState({ icon = "info", title, text, action }: { icon?: IconName; title: ReactNode; text?: ReactNode; action?: ReactNode }) {
  return (
    <div className="grid place-items-center rounded-[18px] border border-dashed border-line px-6 py-12 text-center">
      <div className="mb-3 grid h-14 w-14 place-items-center rounded-2xl bg-[color-mix(in_srgb,var(--accent)_14%,transparent)] text-accent">
        <Icon name={icon} size={26} />
      </div>
      <div className="text-lg font-semibold">{title}</div>
      {text && <p className="mt-1 max-w-md text-sm text-muted">{text}</p>}
      {action && <div className="mt-5 flex flex-wrap justify-center gap-2">{action}</div>}
    </div>
  );
}
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const t = useTranslations("common");
  const locale = useLocale();
  return (
    <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-[14px] border border-red/40 bg-[color-mix(in_srgb,var(--red)_8%,transparent)] px-4 py-3 text-sm">
      <span className="flex items-center gap-2 text-red">
        <Icon name="warn" size={18} />
        {errorText(error, locale) || t("error")}
      </span>
      {onRetry && (
        <Button size="sm" variant="ghost" onClick={onRetry} icon="refresh">
          {t("retry")}
        </Button>
      )}
    </div>
  );
}
export function errorText(e: unknown, locale: string): string {
  if (e instanceof ApiError) return e.text(locale);
  if (e instanceof Error) return e.message;
  return "";
}

/** upsell card for a missing plan feature (403 feature_not_in_plan) */
export function Upsell({ feature }: { feature: string }) {
  const t = useTranslations("upsell");
  const f = useTranslations("features");
  return (
    <div className="rounded-[18px] border border-[color-mix(in_srgb,var(--accent)_40%,transparent)] bg-gradient-to-br from-[color-mix(in_srgb,var(--accent)_12%,transparent)] to-transparent p-6 text-center sm:p-10">
      <div className="mx-auto mb-3 grid h-14 w-14 place-items-center rounded-2xl bg-[color-mix(in_srgb,var(--accent)_18%,transparent)] text-accent">
        <Icon name="crown" size={26} />
      </div>
      <h2 className="text-xl font-bold">{t("title")}</h2>
      <p className="mx-auto mt-1 max-w-md text-sm text-muted">{t("text", { feature: f(feature) })}</p>
      <Link href="/app/settings?tab=plan" className="mt-5 inline-flex rounded-xl bg-accent px-5 py-2.5 text-sm font-medium text-on-accent">
        {t("cta")}
      </Link>
    </div>
  );
}

/* ---------- Modal ---------- */
export function Modal({ open, onClose, title, children, footer, wide }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const tid = useId();
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab" && ref.current) {
        const f = ref.current.querySelectorAll<HTMLElement>('button,[href],input,select,textarea,[tabindex]:not([tabindex="-1"])');
        if (!f.length) return;
        const first = f[0];
        const last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    const timer = setTimeout(() => ref.current?.querySelector<HTMLElement>("[data-autofocus],button,input,select")?.focus(), 30);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      clearTimeout(timer);
      document.body.style.overflow = "";
      prev?.focus?.();
    };
  }, [open, onClose]);
  if (!open || typeof document === "undefined") return null;
  return createPortal(
    <div className="fixed inset-0 z-[60] grid place-items-center bg-black/65 p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={tid}
        className={cx("pop max-h-[90dvh] w-full overflow-auto rounded-[18px] border border-line bg-surface p-5 shadow-2xl sm:p-[22px]", wide ? "max-w-2xl" : "max-w-[440px]")}
      >
        <h4 id={tid} className="mb-2 text-lg font-semibold">
          {title}
        </h4>
        {children}
        {footer && <div className="mt-5 flex gap-2">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

export function ConfirmModal({
  open,
  title,
  text,
  confirmLabel,
  danger,
  onConfirm,
  onClose,
  busy,
}: {
  open: boolean;
  title: ReactNode;
  text?: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onClose: () => void;
  busy?: boolean;
}) {
  const t = useTranslations("common");
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      footer={
        <>
          <Button variant="ghost" className="flex-1" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button variant={danger ? "danger" : "primary"} className="flex-1" onClick={onConfirm} loading={busy}>
            {confirmLabel || t("confirm")}
          </Button>
        </>
      }
    >
      {text && <p className="text-sm text-muted">{text}</p>}
    </Modal>
  );
}

/* number + unit that never reverses in RTL */
export function Num({ v, unit, className }: { v: ReactNode; unit?: string; className?: string }) {
  return (
    <span dir="ltr" className={cx("num", className)}>
      {v}
      {unit ? <span className="ms-1 text-[.6em] font-medium text-muted">{unit}</span> : null}
    </span>
  );
}
