import type { Locale } from "./api";

export const dash = "—";

export function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** latin digits everywhere: keeps numbers consistent and readable in both locales */
export function fmt(v: number | null | undefined, digits = 0): string {
  if (!isNum(v)) return dash;
  return v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtHours(h: number | null | undefined): string {
  if (!isNum(h)) return dash;
  const total = Math.round(h * 60);
  const hh = Math.floor(total / 60);
  const mm = total % 60;
  return `${hh}:${String(mm).padStart(2, "0")}`;
}

export function timeAgoSeconds(iso: string | null | undefined, now = Date.now()): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return Math.max(0, Math.round((now - t) / 1000));
}

export function fmtTime(iso: string, locale: Locale, opts?: Intl.DateTimeFormatOptions): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return dash;
  return d.toLocaleTimeString(locale === "ar" ? "ar-SY-u-nu-latn" : "en-GB", { hour: "2-digit", minute: "2-digit", hour12: false, ...opts });
}
export function fmtDate(iso: string, locale: Locale, opts?: Intl.DateTimeFormatOptions): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return dash;
  return d.toLocaleDateString(locale === "ar" ? "ar-SY-u-nu-latn" : "en-GB", { day: "numeric", month: "short", year: "numeric", ...opts });
}
export function fmtDateTime(iso: string, locale: Locale): string {
  return `${fmtDate(iso, locale, { year: undefined })} ${fmtTime(iso, locale)}`;
}

export function ymd(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
export function startOfDay(d = new Date()): Date {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

export function relTime(iso: string, locale: Locale): string {
  const s = timeAgoSeconds(iso);
  if (s === null) return dash;
  const rtf = new Intl.RelativeTimeFormat(locale === "ar" ? "ar-u-nu-latn" : "en", { numeric: "auto" });
  if (s < 60) return rtf.format(-s, "second");
  if (s < 3600) return rtf.format(-Math.round(s / 60), "minute");
  if (s < 86400) return rtf.format(-Math.round(s / 3600), "hour");
  return rtf.format(-Math.round(s / 86400), "day");
}

export function downloadCsv(filename: string, rows: (string | number | null)[][]) {
  const esc = (v: string | number | null) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const csv = "﻿" + rows.map((r) => r.map(esc).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
