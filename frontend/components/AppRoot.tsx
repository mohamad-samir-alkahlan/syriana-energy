"use client";

import type { ReactNode } from "react";
import { SWRConfig } from "swr";
import { useRouter } from "@/i18n/navigation";
import { ApiError, type Me } from "@/lib/api";
import { MeProvider, useMe } from "@/lib/hooks";
import { onColor, safeColor } from "@/lib/color";
import { BrandingProvider } from "./Providers";
import { AppShell } from "./AppShell";

/** Inside the app the signed-in tenant's own branding wins (an installer sees its brand; its customers inherit it),
 *  not only on the custom domain. `!important` beats the inline vars the root layout sets from the Host. */
function TenantBranding({ children }: { children: ReactNode }) {
  const { me } = useMe();
  const b = me.tenant.branding;
  const primary = safeColor(b.primary_color, "#DA7756");
  const accent2 = safeColor(b.accent_color, "#d9b86b");
  const css = `:root{--accent:${primary}!important;--accent2:${accent2}!important;--on-accent:${onColor(primary)}!important}`;
  return (
    <BrandingProvider branding={b}>
      <style dangerouslySetInnerHTML={{ __html: css }} />
      {children}
    </BrandingProvider>
  );
}

export function AppRoot({ me, children }: { me: Me; children: ReactNode }) {
  const router = useRouter();
  return (
    <SWRConfig
      value={{
        onError: (e) => {
          if (e instanceof ApiError && e.status === 401) router.replace("/login");
        },
      }}
    >
      <MeProvider initial={me}>
        <TenantBranding>
          <AppShell>{children}</AppShell>
        </TenantBranding>
      </MeProvider>
    </SWRConfig>
  );
}
