import type { Metadata, Viewport } from "next";
import type { CSSProperties, ReactNode } from "react";
import { notFound } from "next/navigation";
import { hasLocale, NextIntlClientProvider } from "next-intl";
import { getMessages, setRequestLocale } from "next-intl/server";
import { routing } from "@/i18n/routing";
import { getBranding } from "@/lib/server";
import { onColor, safeColor } from "@/lib/color";
import { BrandingProvider, ToastProvider } from "@/components/Providers";
import "../globals.css";

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params;
  const b = await getBranding();
  const name = locale === "ar" ? b.name_ar || b.name : b.name;
  return {
    title: { default: name, template: `%s · ${name}` },
    description:
      locale === "ar"
        ? "مراقبة والتحكم بمنظومات الطاقة الشمسية: إنفرتر وبطارية ليثيوم."
        : "Monitor and control home solar systems: inverter and lithium battery.",
    manifest: "/manifest.webmanifest",
    icons: b.logo_url ? { icon: b.logo_url, apple: b.logo_url } : undefined,
    appleWebApp: { capable: true, title: name, statusBarStyle: "black-translucent" },
  };
}

export const viewport: Viewport = {
  themeColor: "#0a0a0c",
  width: "device-width",
  initialScale: 1,
};

const themeScript = `try{var t=localStorage.getItem("se_theme");if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}catch(e){}`;

export default async function LocaleLayout({ children, params }: { children: ReactNode; params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  setRequestLocale(locale);
  const [messages, branding] = await Promise.all([getMessages(), getBranding()]);
  const primary = safeColor(branding.primary_color, "#DA7756");
  const accent2 = safeColor(branding.accent_color, "#d9b86b");
  const style = {
    "--accent": primary,
    "--accent2": accent2,
    "--on-accent": onColor(primary),
  } as CSSProperties;

  return (
    <html lang={locale} dir={locale === "ar" ? "rtl" : "ltr"} data-theme="dark" style={style} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>
        <NextIntlClientProvider locale={locale} messages={messages}>
          <BrandingProvider branding={branding}>
            <ToastProvider>{children}</ToastProvider>
          </BrandingProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
