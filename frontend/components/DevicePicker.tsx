"use client";

import { useTranslations } from "next-intl";
import { useDevices } from "@/lib/hooks";
import { Dot, Select, Skeleton } from "./ui";

export function DevicePicker({ kinds }: { kinds?: string[] }) {
  const t = useTranslations("common");
  const { devices, selected, select, loading } = useDevices();
  const list = kinds ? devices.filter((d) => kinds.includes(d.kind)) : devices;
  if (loading) return <Skeleton className="h-[42px] w-48" />;
  if (list.length === 0) return null;
  if (list.length === 1)
    return (
      <span className="inline-flex items-center gap-2 rounded-full border border-line bg-panel px-3 py-1.5 text-sm">
        <Dot on={list[0].online} />
        <b className="font-semibold">{list[0].name}</b>
      </span>
    );
  return (
    <div className="flex items-center gap-2">
      <Dot on={!!selected?.online} />
      <Select aria-label={t("device")} value={selected?.id ?? ""} onChange={(e) => select(e.target.value)} className="min-w-44 !py-2">
        {list.map((d) => (
          <option key={d.id} value={d.id}>
            {d.name}
          </option>
        ))}
      </Select>
    </div>
  );
}

