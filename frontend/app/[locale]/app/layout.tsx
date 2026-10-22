import type { ReactNode } from "react";
import { setRequestLocale } from "next-intl/server";
import { redirect } from "@/i18n/navigation";
import { getMe } from "@/lib/server";
import { AppRoot } from "@/components/AppRoot";

export default async function AppLayout({ children, params }: { children: ReactNode; params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const me = await getMe();
  if (!me) redirect({ href: "/login", locale });
  return <AppRoot me={me!}>{children}</AppRoot>;
}
