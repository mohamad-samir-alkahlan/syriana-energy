import createMiddleware from "next-intl/middleware";
import { routing } from "./i18n/routing";

export default createMiddleware(routing);

export const config = {
  // Everything except API, MCP, Next internals, the manifest and static files.
  matcher: ["/((?!api|mcp|_next|_vercel|manifest\\.webmanifest|.*\\..*).*)"],
};
