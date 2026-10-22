import type { SVGProps } from "react";

const P: Record<string, string> = {
  bolt: "M13 2 4 14h7l-1 8 9-12h-7z",
  bell: "M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10 21h4",
  gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z",
  home: "M3 11l9-8 9 8M5 10v10h14V10",
  chart: "M3 20h18M6 20V10M12 20V4M18 20v-7",
  sliders: "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4",
  flow: "M5 6h5a3 3 0 0 1 3 3v6a3 3 0 0 0 3 3h3M8 3 5 6l3 3M16 15l3 3-3 3",
  chat: "M4 5h16v11H9l-5 4z",
  device: "M5 4h14v12H5zM9 20h6M12 16v4",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
  users: "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM2 20a7 7 0 0 1 14 0M16 4.5a3.5 3.5 0 0 1 0 6.5M18 14a7 7 0 0 1 4 6",
  palette: "M12 3a9 9 0 1 0 0 18c1.2 0 1.8-.8 1.5-1.8-.4-1.2.4-2.2 1.6-2.2H17a4 4 0 0 0 4-4C21 6.6 17 3 12 3zM7.5 11h.01M10 7.5h.01M14.5 7.5h.01",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
  sun: "M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1",
  moon: "M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z",
  plus: "M12 5v14M5 12h14",
  check: "M5 12l5 5 9-10",
  x: "M6 6l12 12M18 6 6 18",
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3",
  edit: "M4 20h4L19 9l-4-4L4 16zM14 6l4 4",
  logout: "M10 4H5v16h5M15 8l4 4-4 4M19 12H9",
  menu: "M4 6h16M4 12h16M4 18h16",
  arrow: "M19 12H5M11 6l-6 6 6 6",
  arrowR: "M5 12h14M13 6l6 6-6 6",
  chevD: "M6 9l6 6 6-6",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 8v5M12 16v.5",
  warn: "M12 3 2 20h20zM12 10v5M12 17.5v.5",
  download: "M12 4v12M7 11l5 5 5-5M5 20h14",
  copy: "M9 9h11v11H9zM5 15V4h11",
  key: "M21 2l-9.6 9.6M15.5 7.5l3 3L22 7l-3-3M7.5 20a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9z",
  lock: "M6 11h12v10H6zM8 11V8a4 4 0 0 1 8 0v3",
  send: "M4 12 20 4l-4 16-4-6z",
  battery: "M3 8h16v8H3zM21 11v2M6 11h5",
  grid: "M12 3 8 21M12 3l4 18M9.5 10h5M8.5 15h7M6 7h12",
  globe: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18",
  crown: "M3 8l4 4 5-7 5 7 4-4-2 11H5z",
  refresh: "M20 11a8 8 0 0 0-14-4M4 4v4h4M4 13a8 8 0 0 0 14 4M20 20v-4h-4",
  play: "M7 4l13 8-13 8z",
  link: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3A4 4 0 0 0 11 18.7l1-1",
  mail: "M3 5h18v14H3zM3 6l9 7 9-7",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  eyeOff: "M3 3l18 18M10 6a9 9 0 0 1 12 6 12 12 0 0 1-3 3.5M6.5 7.5A12 12 0 0 0 2 12s4 7 10 7a9 9 0 0 0 4-1M9.9 9.9a3 3 0 0 0 4.2 4.2",
  external: "M14 4h6v6M20 4l-9 9M18 14v6H4V6h6",
  admin: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM9 12l2 2 4-4",
};

export type IconName = keyof typeof P;

export function Icon({ name, size = 18, ...rest }: { name: IconName; size?: number } & Omit<SVGProps<SVGSVGElement>, "name">) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      <path d={P[name]} />
    </svg>
  );
}

/** the brand mark from the approved mockup */
export function LogoMark({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <circle cx="16" cy="16" r="14" fill="none" stroke="var(--accent)" strokeWidth="2" />
      <path d="M18 5 L10 18 H16 L14 27 L22 14 H16 Z" fill="var(--accent)" />
    </svg>
  );
}
