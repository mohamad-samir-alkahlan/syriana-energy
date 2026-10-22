import { getBranding } from "@/lib/server";
import { safeColor } from "@/lib/color";

export const dynamic = "force-dynamic";

export async function GET() {
  const b = await getBranding();
  const color = safeColor(b.primary_color, "#DA7756");
  const icons = b.logo_url
    ? [
        { src: b.logo_url, sizes: "192x192", type: "image/png", purpose: "any" },
        { src: b.logo_url, sizes: "512x512", type: "image/png", purpose: "any" },
      ]
    : [{ src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" }];
  const body = {
    name: b.name,
    short_name: b.name.slice(0, 12),
    description: b.name_ar,
    start_url: "/ar/app",
    scope: "/",
    display: "standalone",
    background_color: "#0a0a0c",
    theme_color: color,
    lang: "ar",
    dir: "rtl",
    icons,
  };
  return new Response(JSON.stringify(body), {
    headers: { "content-type": "application/manifest+json", "cache-control": "no-store" },
  });
}
