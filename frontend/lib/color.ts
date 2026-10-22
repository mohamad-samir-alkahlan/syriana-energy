const HEX = /^#([0-9a-f]{6}|[0-9a-f]{3})$/i;

export function safeColor(c: string | null | undefined, fallback: string): string {
  return c && HEX.test(c.trim()) ? c.trim() : fallback;
}

export function luminance(hex: string): number {
  let h = hex.replace("#", "");
  if (h.length === 3) h = h.split("").map((x) => x + x).join("");
  const [r, g, b] = [0, 2, 4].map((i) => {
    const v = parseInt(h.slice(i, i + 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** readable text colour on top of a given background */
export function onColor(hex: string): string {
  return luminance(hex) > 0.45 ? "#17171a" : "#ffffff";
}
