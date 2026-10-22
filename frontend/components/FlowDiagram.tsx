"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import type { Metrics } from "@/lib/api";
import { fmt, isNum } from "@/lib/format";

const LRI = "⁦";
const PDI = "⁩";
/** wrap a value so it stays left-to-right inside RTL text (fixes the "W 1312" reversal) */
const L = (s: string) => `${LRI}${s}${PDI}`;

type NodeKey = "inv" | "grid" | "sun" | "bat" | "home";
type Pt = [number, number];

/**
 * Two geometries of the same diagram. "wide" is the approved mockup (1000x470).
 * "tall" is a compact portrait variant used below the sm breakpoint so text stays readable at 390px.
 * Icon artwork is authored around the mockup's node centres; `ICON_ORIGIN` maps it onto any layout.
 */
const ICON_ORIGIN: Record<NodeKey, Pt> = { grid: [180, 110], sun: [820, 110], inv: [500, 238], bat: [180, 360], home: [820, 360] };

interface Layout {
  vb: Pt;
  pos: Record<NodeKey, Pt>;
  r: number;
  rInv: number;
  k: number; // icon scale
  fs: { big: number; mid: number; sm: number };
  // text offsets (dy of main line, dy of sub line) from node centre
  dy: Record<NodeKey, Pt>;
  paths: { grid: string; sun: string; home: string; charge: string; discharge: string };
  lbl: { grid: Pt; sun: Pt; home: Pt; bat: Pt };
}
const WIDE: Layout = {
  vb: [1000, 470],
  pos: { grid: [180, 110], sun: [820, 110], inv: [500, 238], bat: [180, 360], home: [820, 360] },
  r: 50,
  rInv: 56,
  k: 1,
  fs: { big: 24, mid: 15, sm: 13 },
  dy: { grid: [76, 96], sun: [76, 96], inv: [80, 100], bat: [72, 92], home: [72, 92] },
  paths: {
    grid: "M235 115 C 330 115, 390 180, 455 215",
    sun: "M765 115 C 670 115, 610 180, 548 212",
    home: "M548 262 C 610 300, 670 355, 760 358",
    charge: "M452 262 C 390 300, 330 355, 242 358",
    discharge: "M242 358 C 330 355, 390 300, 452 262",
  },
  lbl: { grid: [326, 152], sun: [666, 142], home: [692, 334], bat: [392, 384] },
};
const TALL: Layout = {
  vb: [420, 600],
  pos: { grid: [78, 78], sun: [342, 78], inv: [210, 290], bat: [78, 500], home: [342, 500] },
  r: 40,
  rInv: 46,
  k: 0.8,
  fs: { big: 21, mid: 14, sm: 11.5 },
  dy: { grid: [62, 80], sun: [62, 80], inv: [72, 90], bat: [62, 80], home: [62, 80] },
  paths: {
    grid: "M108 108 C 140 160, 165 215, 182 252",
    sun: "M312 108 C 280 160, 255 215, 238 252",
    home: "M236 334 C 262 380, 300 430, 330 458",
    charge: "M184 334 C 158 380, 120 430, 90 458",
    discharge: "M90 458 C 120 430, 158 380, 184 334",
  },
  lbl: { grid: [112, 196], sun: [308, 196], home: [300, 428], bat: [120, 428] },
};

export function FlowDiagram({ metrics, online, model }: { metrics: Metrics | null | undefined; online: boolean; model?: string | null }) {
  const t = useTranslations("flow");
  const baseId = useId().replace(/:/g, "");
  const [active, setActive] = useState<NodeKey | null>(null);
  const m = metrics || {};

  const pv = isNum(m.pv_power) ? m.pv_power : null;
  const load = isNum(m.load_power) ? m.load_power : null;
  const bp = isNum(m.battery_power) ? m.battery_power : null;
  const soc = isNum(m.battery_soc) ? m.battery_soc : null;
  const gridOn = m.grid_available === true;
  const gridKnown = typeof m.grid_available === "boolean";

  const sunFlow = online && pv !== null && pv > 5;
  const homeFlow = online && load !== null && load > 5;
  const charging = online && bp !== null && bp > 5;
  const discharging = online && bp !== null && bp < -5;
  const gridFlow = online && gridOn && (m.grid_power == null || m.grid_power > 5 || pv === null || pv < (load ?? 0));

  const w = (n: number | null | undefined) => (isNum(n) ? `${L(fmt(n))} ${t("w")}` : "—");
  const v = (n: number | null | undefined, d = 1) => (isNum(n) ? L(`${fmt(n, d)}V`) : "—");
  const pc = (n: number | null | undefined) => (isNum(n) ? L(`${fmt(n)}%`) : "—");
  const am = (n: number | null | undefined) => (isNum(n) ? L(`${fmt(n, 1)}A`) : "—");

  const batState = !online || bp === null ? "" : charging ? t("charging") : discharging ? t("discharging") : t("idle");
  const modeLabel = t(`mode_${m.mode || "unknown"}`);

  const caps: Record<NodeKey, string> = {
    inv: t("cap_inv", { mode: modeLabel }),
    grid: gridKnown ? (gridOn ? t("cap_grid_on", { v: v(m.grid_voltage) }) : t("cap_grid_off")) : t("cap_grid_unknown"),
    sun: pv !== null ? t("cap_sun", { w: w(pv), v: v(m.pv_voltage), a: am(m.pv_current) }) : t("cap_unknown"),
    bat: soc !== null ? t("cap_bat", { soc: pc(soc), v: v(m.battery_voltage), state: batState || "—" }) : t("cap_unknown"),
    home: load !== null ? t("cap_home", { w: w(load), pct: pc(m.load_percent) }) : t("cap_unknown"),
  };

  const sub = {
    inv: `${modeLabel}${isNum(m.inverter_temperature) ? ` · ${L(`${fmt(m.inverter_temperature)}°C`)}` : ""}${isNum(m.bus_voltage) ? ` · ${L(`BUS ${fmt(m.bus_voltage)}V`)}` : ""}`,
    grid: gridKnown ? `${v(gridOn ? m.grid_voltage : 0)} · ${gridOn ? t("available") : t("lost")}` : "—",
    sun: `${t("panels")} · ${v(m.pv_voltage)}${isNum(m.pv_current) ? ` · ${am(m.pv_current)}` : ""}`,
    bat: `${t("battery")} · ${v(m.battery_voltage)}${batState ? ` · ${batState}` : ""}`,
    home: `${t("home_load")}${isNum(m.load_percent) ? ` · ${pc(m.load_percent)}` : ""}${isNum(m.output_voltage) ? ` · ${v(m.output_voltage, 0)}` : ""}`,
  };
  const main = {
    inv: model ? t("inverter_model", { model }) : t("inverter"),
    grid: t("grid"),
    sun: w(pv),
    bat: pc(soc),
    home: w(load),
  };

  return (
    <div className="relative rounded-[20px] border border-line bg-bg2 p-2 [background-image:radial-gradient(circle,var(--grid-dot)_1px,transparent_1px)] [background-size:24px_24px] sm:p-2.5">
      <div className="sm:hidden">
        {renderSvg(TALL, "t")}
      </div>
      <div className="hidden sm:block">
        {renderSvg(WIDE, "w")}
      </div>

      {!online && (
        <div className="pointer-events-none absolute inset-x-0 top-[38%] grid place-items-center">
          <span className="rounded-full border border-red/50 bg-surface px-4 py-2 text-sm text-red shadow-lg">{t("offline")}</span>
        </div>
      )}

      <div className="mx-1 mb-1 mt-1.5 min-h-[44px] rounded-xl border border-line bg-panel px-3.5 py-2.5 text-sm text-muted sm:mx-2.5" aria-live="polite">
        {active ? (
          <span>
            <b className="text-fg">{t(`name_${active}`)}:</b> {caps[active]}
          </span>
        ) : (
          t("hint")
        )}
      </div>
    </div>
  );

  function renderSvg(lay: Layout, id: string) {
    const uid = baseId + id;
    const { pos: P, r, rInv, k, fs, dy, paths, lbl } = lay;
    const icon = (key: NodeKey) => `translate(${P[key][0]} ${P[key][1]}) scale(${key === "inv" ? k * (rInv / 56) : k}) translate(${-ICON_ORIGIN[key][0]} ${-ICON_ORIGIN[key][1]})`;
    const ts = (size: number, weight?: number) => ({ fontSize: size, fontWeight: weight });
    const mk = (mid: string, color: string) => (
      <marker id={`${uid}${mid}`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto">
        <path d="M0 0 L10 5 L0 10 z" fill={color} />
      </marker>
    );
    const np = (key: NodeKey, label: string) => ({
      className: "node",
      role: "button" as const,
      tabIndex: 0,
      "aria-label": label,
      onMouseEnter: () => setActive(key),
      onFocus: () => setActive(key),
      onClick: () => setActive(key),
      onKeyDown: (e: React.KeyboardEvent) => (e.key === "Enter" || e.key === " ") && setActive(key),
      style: { transformOrigin: `${P[key][0]}px ${P[key][1]}px` },
    });
    const socFill = soc !== null ? Math.max(0, Math.min(100, soc)) / 100 : 0;
    const socColor = soc !== null && soc < 20 ? "var(--red)" : "var(--green)";
    const gc = gridOn && online ? "var(--blue)" : "var(--muted)";
    const lab = (key: NodeKey, big: boolean) => (
      <>
        <text x={P[key][0]} y={P[key][1] + dy[key][0]} textAnchor="middle" className={big ? "t-big" : "t-mid"} style={ts(big ? fs.big : fs.mid)}>
          {main[key]}
        </text>
        <text x={P[key][0]} y={P[key][1] + dy[key][1]} textAnchor="middle" className="t-sm" style={ts(fs.sm)}>
          {sub[key]}
        </text>
      </>
    );
    const flowLabel = (pt: Pt, text: string, color?: string) => (
      <text x={pt[0]} y={pt[1]} className="t-sm" fill={color} style={ts(fs.sm)} textAnchor="middle">
        {text}
      </text>
    );

    return (
      <svg viewBox={`0 0 ${lay.vb[0]} ${lay.vb[1]}`} className="block h-auto w-full" role="img" aria-label={t("title")} style={{ opacity: online ? 1 : 0.42, transition: "opacity .4s" }}>
        <defs>
          <filter id={`${uid}glow`} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation={lay === TALL ? 10 : 14} />
          </filter>
          {mk("g", "var(--gold)")}
          {mk("b", "var(--green)")}
          {mk("h", "var(--accent)")}
          {mk("n", "var(--blue)")}
        </defs>

        {/* grid -> inverter */}
        {gridFlow ? (
          <>
            <path className="flow" stroke="var(--blue)" markerEnd={`url(#${uid}n)`} d={paths.grid} />
            {isNum(m.grid_power) && flowLabel(lbl.grid, w(m.grid_power), "var(--blue)")}
          </>
        ) : (
          <>
            <path className="flow-off" d={paths.grid} />
            {gridKnown && !gridOn && flowLabel(lbl.grid, t("no_current"))}
          </>
        )}

        {/* sun -> inverter */}
        {sunFlow ? (
          <>
            <path className="flow" stroke="var(--gold)" markerEnd={`url(#${uid}g)`} d={paths.sun} />
            {flowLabel(lbl.sun, w(pv), "var(--gold)")}
          </>
        ) : (
          <path className="flow-off" d={paths.sun} />
        )}

        {/* inverter -> home */}
        {homeFlow ? (
          <>
            <path className="flow slow" stroke="var(--accent)" markerEnd={`url(#${uid}h)`} d={paths.home} />
            {flowLabel(lbl.home, w(load), "var(--accent)")}
          </>
        ) : (
          <path className="flow-off" d={paths.home} />
        )}

        {/* inverter <-> battery */}
        {charging && (
          <>
            <path className="flow" stroke="var(--green)" markerEnd={`url(#${uid}b)`} d={paths.charge} />
            {flowLabel(lbl.bat, t("charge_w", { w: w(bp) }), "var(--green)")}
          </>
        )}
        {discharging && (
          <>
            <path className="flow" stroke="var(--accent)" markerEnd={`url(#${uid}h)`} d={paths.discharge} />
            {flowLabel(lbl.bat, t("discharge_w", { w: w(bp !== null ? Math.abs(bp) : null) }), "var(--accent)")}
          </>
        )}
        {!charging && !discharging && <path className="flow-off" d={paths.charge} />}

        {/* INVERTER */}
        <g {...np("inv", t("inverter"))}>
          <circle cx={P.inv[0]} cy={P.inv[1]} r={rInv + 14} fill="var(--accent)" opacity=".22" filter={`url(#${uid}glow)`}>
            {online && <animate attributeName="opacity" values=".12;.3;.12" dur="3s" repeatCount="indefinite" />}
          </circle>
          <circle className="node-ring" cx={P.inv[0]} cy={P.inv[1]} r={rInv} stroke="var(--accent)" />
          <g className="ico" stroke="var(--accent)" transform={icon("inv")}>
            <rect x="474" y="216" width="52" height="38" rx="5" />
            <path d="M482 228h14M482 238h10" />
            <path d="M506 228 l8 0 -6 12 h8" />
          </g>
          {lab("inv", false)}
        </g>

        {/* GRID */}
        <g {...np("grid", t("grid"))} opacity={gridOn && online ? 1 : 0.6}>
          <circle className="node-ring" cx={P.grid[0]} cy={P.grid[1]} r={r} stroke={gc} />
          <g className="ico" stroke={gc} transform={icon("grid")}>
            <path d="M180 82 L166 140 M180 82 L194 140 M170 104h20 M167 120h26 M180 82v58" />
            <path d="M160 92h40" />
          </g>
          {lab("grid", false)}
        </g>

        {/* SUN */}
        <g {...np("sun", t("sun"))}>
          <circle cx={P.sun[0]} cy={P.sun[1]} r={r + 10} fill="var(--gold)" opacity={sunFlow ? 0.15 : 0.05} filter={`url(#${uid}glow)`} />
          <circle className="node-ring" cx={P.sun[0]} cy={P.sun[1]} r={r} stroke="var(--gold)" />
          <g className="ico" stroke="var(--gold)" transform={icon("sun")}>
            <circle cx="820" cy="104" r="11" />
            <path d="M820 82v-6M820 132v-6M798 104h-6M848 104h-6M804 88l-4-4M840 124l-4-4M836 88l4-4M800 124l4-4" />
            <path d="M800 136h40" />
          </g>
          {lab("sun", true)}
        </g>

        {/* BATTERY */}
        <g {...np("bat", t("battery"))}>
          <circle className="node-ring" cx={P.bat[0]} cy={P.bat[1]} r={r} stroke={socColor} />
          <g className="ico" stroke={socColor} transform={icon("bat")}>
            <rect x="160" y="342" width="36" height="40" rx="4" transform="rotate(-90 178 362)" />
            <path d="M200 356v12" />
            <rect className="" x="162" y="354" width={25 * socFill} height="14" rx="2" fill={socColor} stroke="none" opacity=".75" />
          </g>
          {lab("bat", true)}
        </g>

        {/* HOME */}
        <g {...np("home", t("home"))}>
          <circle className="node-ring" cx={P.home[0]} cy={P.home[1]} r={r} stroke="var(--accent)" />
          <g className="ico" stroke="var(--accent)" transform={icon("home")}>
            <path d="M796 364 L820 342 L844 364" />
            <path d="M802 358v24h36v-24" />
            <rect x="815" y="368" width="10" height="14" />
          </g>
          {lab("home", true)}
        </g>
      </svg>
    );
  }
}
