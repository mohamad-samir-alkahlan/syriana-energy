import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./i18n/request.ts");
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` },
      { source: "/mcp", destination: `${BACKEND_URL}/mcp` },
      { source: "/mcp/:path*", destination: `${BACKEND_URL}/mcp/:path*` },
    ];
  },
};

export default withNextIntl(nextConfig);
