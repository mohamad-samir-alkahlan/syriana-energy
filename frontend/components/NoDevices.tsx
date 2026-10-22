"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { addDemoDevice } from "@/lib/demo";
import { useDevices } from "@/lib/hooks";
import { Button, EmptyState, errorText } from "./ui";
import { useToast } from "./Providers";
import { useLocale } from "next-intl";

export function NoDevices() {
  const t = useTranslations("empty");
  const locale = useLocale();
  const { reload } = useDevices();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const demo = async () => {
    setBusy(true);
    try {
      await addDemoDevice(t("demo_site"), t("demo_device"));
      await reload();
      toast(t("demo_added"));
    } catch (e) {
      toast(errorText(e, locale), "err");
    } finally {
      setBusy(false);
    }
  };
  return (
    <EmptyState
      icon="device"
      title={t("title")}
      text={t("text")}
      action={
        <>
          <Link href="/app/devices?add=1" className="inline-flex items-center gap-2 rounded-xl border border-accent bg-accent px-4 py-2.5 text-sm font-medium text-on-accent">
            {t("add")}
          </Link>
          <Button variant="ghost" icon="play" onClick={demo} loading={busy}>
            {t("try_demo")}
          </Button>
        </>
      }
    />
  );
}
