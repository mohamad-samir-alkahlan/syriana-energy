"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useLocale } from "next-intl";
import { fmt, isNum } from "@/lib/format";

export function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    setW(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

export interface Series {
  key: string;
  label: string;
  color: string;
  axis?: "l" | "r";
  kind?: "area" | "line";
  dashed?: boolean;
  unit?: string;
  data: [number, number | null][]; // [epoch ms, value]
}
export interface Band {
  from: number;
  to: number;
  color: string;
  label?: string;
}

function niceMax(v: number) {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / p;
  const m = n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10;
  return m * p;
}

function tickHours(t0: number, t1: number, maxTicks: number): number[] {
  const span = t1 - t0;
  const steps = [1, 2, 3, 6, 12, 24, 48, 72, 168, 336, 720].map((h) => h * 3600_000);
  const step = steps.find((s) => span / s <= maxTicks) ?? steps[steps.length - 1];
  const out: number[] = [];
  let first = Math.ceil(t0 / step) * step;
  // align to local midnight for multi-hour steps
  const d = new Date(t0);
  d.setHours(0, 0, 0, 0);
  if (step >= 3600_000) {
    first = d.getTime();
    while (first < t0) first += step;
  }
  for (let t = first; t <= t1; t += step) out.push(t);
  return out;
}

export function TimeChart({
  series,
  t0,
  t1,
  bands = [],
  now,
  height = 260,
  rightMax = 100,
  rightUnit = "%",
  leftUnit = "W",
  emptyText,
}: {
  series: Series[];
  t0: number;
  t1: number;
  bands?: Band[];
  now?: number;
  height?: number;
  rightMax?: number;
  rightUnit?: string;
  leftUnit?: string;
  emptyText?: string;
}) {
  const locale = useLocale();
  const [ref, w] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const hasRight = series.some((s) => s.axis === "r");
  const padL = 54;
  const padR = hasRight ? 38 : 12;
  const padT = 14;
  const padB = 30;
  const W = Math.max(w, 260);
  const iw = W - padL - padR;
  const ih = height - padT - padB;

  const [lMin, lMax] = useMemo(() => {
    let mx = 0;
    let mn = 0;
    for (const s of series)
      if (s.axis !== "r")
        for (const [, v] of s.data) {
          if (!isNum(v)) continue;
          if (v > mx) mx = v;
          if (v < mn) mn = v;
        }
    const top = niceMax(mx * 1.08);
    const bottom = mn < 0 ? -niceMax(-mn * 1.08) : 0;
    return [bottom, top] as const;
  }, [series]);
  const span = lMax - lMin || 1;

  const x = (t: number) => padL + ((t - t0) / (t1 - t0 || 1)) * iw;
  const yL = (v: number) => padT + ih - ((v - lMin) / span) * ih;
  const yR = (v: number) => padT + ih - (v / rightMax) * ih;
  const yOf = (s: Series, v: number) => (s.axis === "r" ? yR(v) : yL(v));

  const path = (s: Series, area: boolean) => {
    let d = "";
    let seg: [number, number][] = [];
    const flush = () => {
      if (!seg.length) return;
      d += seg.map(([px, py], i) => `${i ? "L" : "M"}${px.toFixed(1)} ${py.toFixed(1)}`).join("");
      if (area) {
        const base = yL(0);
        d += `L${seg[seg.length - 1][0].toFixed(1)} ${base}L${seg[0][0].toFixed(1)} ${base}Z`;
      }
      seg = [];
    };
    for (const [t, v] of s.data) {
      if (t < t0 || t > t1) continue;
      if (!isNum(v)) {
        flush();
        continue;
      }
      seg.push([x(t), yOf(s, v)]);
    }
    flush();
    return d;
  };

  const allTs = useMemo(() => {
    const set = new Set<number>();
    for (const s of series) for (const [t] of s.data) if (t >= t0 && t <= t1) set.add(t);
    return [...set].sort((a, b) => a - b);
  }, [series, t0, t1]);

  const onMove = (clientX: number, rect: DOMRect) => {
    if (!allTs.length) return;
    const t = t0 + ((clientX - rect.left - padL) / iw) * (t1 - t0);
    let lo = 0;
    let hi = allTs.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (allTs[mid] < t) lo = mid + 1;
      else hi = mid;
    }
    const cand = [allTs[lo - 1], allTs[lo]].filter((v) => v !== undefined);
    const best = cand.sort((a, b) => Math.abs(a - t) - Math.abs(b - t))[0];
    setHover(best ?? null);
  };

  const ticks = tickHours(t0, t1, Math.max(3, Math.floor(iw / 70)));
  const multiDay = t1 - t0 > 36 * 3600_000;
  const tickLabel = (t: number) => {
    const d = new Date(t);
    if (multiDay) return d.toLocaleDateString(locale === "ar" ? "ar-SY-u-nu-latn" : "en-GB", { day: "numeric", month: "short" });
    return String(d.getHours()).padStart(2, "0");
  };

  const empty = series.every((s) => !s.data.some(([, v]) => isNum(v)));
  const hoverVals = hover !== null ? series.map((s) => ({ s, v: s.data.find(([t]) => t === hover)?.[1] ?? null })) : [];
  const hx = hover !== null ? x(hover) : 0;
  const tipRight = hx > W / 2;

  return (
    <div ref={ref} className="relative w-full" dir="ltr" style={{ height }}>
      {w > 0 && (
        <svg
          width={W}
          height={height}
          role="img"
          onMouseMove={(e) => onMove(e.clientX, e.currentTarget.getBoundingClientRect())}
          onTouchMove={(e) => onMove(e.touches[0].clientX, e.currentTarget.getBoundingClientRect())}
          onMouseLeave={() => setHover(null)}
          style={{ display: "block", touchAction: "pan-y" }}
        >
          {[0, 0.25, 0.5, 0.75, 1].map((f) => {
            const y = padT + ih - f * ih;
            return (
              <g key={f}>
                <line x1={padL} x2={W - padR} y1={y} y2={y} stroke="var(--line)" strokeOpacity={0.7} />
                <text x={padL - 6} y={y + 4} textAnchor="end" fontSize="11" fill="var(--muted)">
                  {f === 1 ? `${fmt(lMin + span * f, span < 10 ? 1 : 0)}${leftUnit}` : fmt(lMin + span * f, span < 10 ? 1 : 0)}
                </text>
                {hasRight && (
                  <text x={W - padR + 6} y={y + 4} fontSize="11" fill="var(--green)">
                    {f === 1 ? `${rightMax * f}${rightUnit}` : rightMax * f}
                  </text>
                )}
              </g>
            );
          })}
          {ticks.map((t) => (
            <text key={t} x={x(t)} y={height - 8} textAnchor="middle" fontSize="11" fill="var(--muted)">
              {tickLabel(t)}
            </text>
          ))}
          {bands.map((b, i) => {
            const a = Math.max(b.from, t0);
            const z = Math.min(b.to, t1);
            if (z <= a) return null;
            return (
              <g key={i}>
                <rect x={x(a)} y={padT} width={Math.max(2, x(z) - x(a))} height={ih} fill={b.color} opacity={0.08} />
                <rect x={x(a)} y={padT + ih - 6} width={Math.max(2, x(z) - x(a))} height={6} rx={3} fill={b.color} opacity={0.75} />
              </g>
            );
          })}
          {series.map((s) =>
            s.kind === "area" ? (
              <g key={s.key}>
                <path d={path(s, true)} fill={s.color} opacity={0.18} />
                <path d={path(s, false)} fill="none" stroke={s.color} strokeWidth={2} />
              </g>
            ) : (
              <path key={s.key} d={path(s, false)} fill="none" stroke={s.color} strokeWidth={2.2} strokeDasharray={s.dashed ? "5 5" : undefined} strokeLinejoin="round" />
            ),
          )}
          {now !== undefined && now >= t0 && now <= t1 && (
            <line x1={x(now)} x2={x(now)} y1={padT} y2={padT + ih} stroke="var(--text)" strokeOpacity={0.3} strokeDasharray="3 4" />
          )}
          {hover !== null && (
            <g>
              <line x1={hx} x2={hx} y1={padT} y2={padT + ih} stroke="var(--text)" strokeOpacity={0.35} />
              {hoverVals.map(({ s, v }) => isNum(v) && <circle key={s.key} cx={hx} cy={yOf(s, v)} r={4} fill={s.color} stroke="var(--bg)" strokeWidth={1.5} />)}
            </g>
          )}
        </svg>
      )}
      {empty && w > 0 && (
        <div className="absolute inset-0 grid place-items-center text-sm text-muted">{emptyText}</div>
      )}
      {hover !== null && (
        <div
          className="pointer-events-none absolute top-2 z-10 rounded-xl border border-line bg-surface px-3 py-2 text-xs shadow-lg"
          style={tipRight ? { right: W - hx + 10 } : { left: hx + 10 }}
        >
          <div className="mb-1 text-muted">
            {new Date(hover).toLocaleString(locale === "ar" ? "ar-SY-u-nu-latn" : "en-GB", multiDay ? { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" } : { hour: "2-digit", minute: "2-digit" })}
          </div>
          {hoverVals.map(({ s, v }) => (
            <div key={s.key} className="flex items-center gap-2 whitespace-nowrap">
              <i className="inline-block h-2 w-2 rounded-sm" style={{ background: s.color }} />
              <span className="text-muted">{s.label}</span>
              <b className="ms-auto ps-3">{isNum(v) ? `${fmt(v, s.unit === "kWh" ? 2 : 0)} ${s.unit ?? ""}` : "—"}</b>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-1.5">
          <i className="inline-block h-2.5 w-2.5 rounded-[3px]" style={{ background: i.color }} />
          {i.label}
        </span>
      ))}
    </div>
  );
}

export interface BarGroup {
  label: string;
  values: { key: string; v: number | null; color: string; name: string }[];
}
export function BarChart({ groups, height = 240, unit = "kWh", emptyText }: { groups: BarGroup[]; height?: number; unit?: string; emptyText?: string }) {
  const [ref, w] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const W = Math.max(w, 260);
  const padL = 40;
  const padR = 8;
  const padT = 12;
  const padB = 28;
  const iw = W - padL - padR;
  const ih = height - padT - padB;
  let max = 0;
  for (const g of groups) for (const v of g.values) if (isNum(v.v) && v.v > max) max = v.v;
  const top = niceMax(max * 1.08);
  const gw = iw / Math.max(groups.length, 1);
  const nb = groups[0]?.values.length || 1;
  const bw = Math.max(2, Math.min(18, (gw * 0.78) / nb));
  const every = Math.ceil(groups.length / Math.max(1, Math.floor(iw / 44)));
  const empty = max === 0;
  return (
    <div ref={ref} className="relative w-full" dir="ltr" style={{ height }}>
      {w > 0 && (
        <svg width={W} height={height} onMouseLeave={() => setHover(null)} style={{ display: "block" }} role="img">
          {[0, 0.25, 0.5, 0.75, 1].map((f) => {
            const y = padT + ih - f * ih;
            return (
              <g key={f}>
                <line x1={padL} x2={W - padR} y1={y} y2={y} stroke="var(--line)" strokeOpacity={0.7} />
                <text x={padL - 6} y={y + 4} textAnchor="end" fontSize="11" fill="var(--muted)">
                  {fmt(top * f, top < 10 ? 1 : 0)}
                </text>
              </g>
            );
          })}
          {groups.map((g, gi) => {
            const cx = padL + gi * gw + gw / 2;
            return (
              <g key={gi} onMouseEnter={() => setHover(gi)} onTouchStart={() => setHover(gi)}>
                <rect x={padL + gi * gw} y={padT} width={gw} height={ih} fill="transparent" />
                {hover === gi && <rect x={padL + gi * gw} y={padT} width={gw} height={ih} fill="var(--text)" opacity={0.05} />}
                {g.values.map((v, vi) => {
                  const h = isNum(v.v) ? (v.v / top) * ih : 0;
                  return <rect key={v.key} x={cx - (bw * nb) / 2 + vi * bw} y={padT + ih - h} width={Math.max(1, bw - 1)} height={h} rx={2} fill={v.color} />;
                })}
                {gi % every === 0 && (
                  <text x={cx} y={height - 9} textAnchor="middle" fontSize="11" fill="var(--muted)">
                    {g.label}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      )}
      {empty && w > 0 && <div className="absolute inset-0 grid place-items-center text-sm text-muted">{emptyText}</div>}
      {hover !== null && groups[hover] && (
        <div
          className="pointer-events-none absolute top-1 z-10 rounded-xl border border-line bg-surface px-3 py-2 text-xs shadow-lg"
          style={padL + hover * gw > W / 2 ? { right: W - (padL + hover * gw) + 6 } : { left: padL + (hover + 1) * gw + 6 }}
        >
          <div className="mb-1 text-muted">{groups[hover].label}</div>
          {groups[hover].values.map((v) => (
            <div key={v.key} className="flex items-center gap-2 whitespace-nowrap">
              <i className="inline-block h-2 w-2 rounded-sm" style={{ background: v.color }} />
              <span className="text-muted">{v.name}</span>
              <b className="ms-auto ps-3">{isNum(v.v) ? `${fmt(v.v, 1)} ${unit}` : "—"}</b>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** tiny area/line sparkline for admin tiles */
export function Sparkline({ data, color = "var(--accent)", height = 60 }: { data: number[]; color?: string; height?: number }) {
  const [ref, w] = useWidth<HTMLDivElement>();
  const max = Math.max(1, ...data);
  const pts = data.map((v, i) => [(i / Math.max(1, data.length - 1)) * (w - 4) + 2, height - 4 - (v / max) * (height - 10)]);
  const d = pts.map(([px, py], i) => `${i ? "L" : "M"}${px.toFixed(1)} ${py.toFixed(1)}`).join("");
  return (
    <div ref={ref} dir="ltr" style={{ height }}>
      {w > 0 && data.length > 1 && (
        <svg width={w} height={height} aria-hidden="true">
          <path d={`${d}L${w - 2} ${height}L2 ${height}Z`} fill={color} opacity={0.15} />
          <path d={d} fill="none" stroke={color} strokeWidth={2} />
        </svg>
      )}
    </div>
  );
}
