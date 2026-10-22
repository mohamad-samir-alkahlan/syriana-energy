import "server-only";
import { headers, cookies } from "next/headers";
import { DEFAULT_BRANDING, qs, type Branding, type Me } from "./api";


export const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

export async function serverFetch<T>(path: string, cookie?: string, query?: Record<string, string>): Promise<T | null> {
  try {
    const res = await fetch(`${BACKEND_URL}/api${path}${qs(query)}`, {
      headers: cookie ? { cookie } : undefined,
      cache: "no-store",
      signal: AbortSignal.timeout(4000),
    });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}


export async function getHost(): Promise<string> {
  const h = await headers();
  return (h.get("x-forwarded-host") || h.get("host") || "localhost").split(",")[0].trim();
}

export async function getBranding(): Promise<Branding> {
  const host = (await getHost()).replace(/:\d+$/, "");
  const b = await serverFetch<Branding>("/public/branding", undefined, { host });
  return { ...DEFAULT_BRANDING, ...(b || {}) };
}

export async function getCookieHeader(): Promise<string> {
  const c = await cookies();
  return c.getAll().map((x) => `${x.name}=${x.value}`).join("; ");
}

export async function getMe(): Promise<Me | null> {
  return serverFetch<Me>("/auth/me", await getCookieHeader());
}
