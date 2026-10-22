"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import useSWR, { mutate as globalMutate, type SWRConfiguration } from "swr";
import { api, ApiError, items, type Device, type Feature, type Me, type Site } from "./api";

/* ---------------- session ---------------- */
interface MeCtx {
  me: Me;
  setMe: (m: Me) => void;
  refresh: () => Promise<void>;
}
const MeContext = createContext<MeCtx | null>(null);

export function MeProvider({ initial, children }: { initial: Me; children: ReactNode }) {
  const [me, setMe] = useState<Me>(initial);
  const refresh = useCallback(async () => {
    try {
      setMe(await api.me());
    } catch {}
  }, []);
  const value = useMemo(() => ({ me, setMe, refresh }), [me, refresh]);
  return <MeContext.Provider value={value}>{children}</MeContext.Provider>;
}
export function useMe() {
  const c = useContext(MeContext);
  if (!c) throw new Error("MeProvider missing");
  return c;
}
export function useHasFeature(f: Feature) {
  return useMe().me.tenant.plan.features.includes(f);
}
export function canWrite(me: Me) {
  return me.role === "owner" || me.role === "admin";
}
/** invalidate everything after switching tenant */
export function resetCache() {
  return globalMutate(() => true, undefined, { revalidate: true });
}

/* ---------------- fetching ---------------- */
export function useApi<T>(key: string | null, fetcher: () => Promise<T>, cfg?: SWRConfiguration<T, ApiError>) {
  return useSWR<T, ApiError>(key, fetcher, {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
    ...cfg,
  });
}

/* ---------------- devices ---------------- */
interface DevCtx {
  sites: Site[];
  devices: Device[];
  selected: Device | null;
  selectedId: string | null;
  select: (id: string) => void;
  loading: boolean;
  error: ApiError | undefined;
  reload: () => Promise<unknown>;
}
const DeviceContext = createContext<DevCtx | null>(null);

export function DeviceProvider({ children }: { children: ReactNode }) {
  const { me } = useMe();
  const { data, error, isLoading, mutate } = useApi(`sites:${me.tenant.id}`, () => api.sites());
  const sites = useMemo(() => items(data), [data]);
  const devices = useMemo(() => sites.flatMap((s) => s.devices || []), [sites]);
  const [pick, setPick] = useState<string | null>(null);
  useEffect(() => {
    try {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setPick(localStorage.getItem("se_device"));
    } catch {}
  }, []);
  const selected = devices.find((d) => d.id === pick) || devices.find((d) => d.kind === "inverter") || devices[0] || null;
  const select = useCallback((id: string) => {
    setPick(id);
    try {
      localStorage.setItem("se_device", id);
    } catch {}
  }, []);
  const value: DevCtx = {
    sites,
    devices,
    selected,
    selectedId: selected?.id ?? null,
    select,
    loading: isLoading,
    error,
    reload: () => mutate(),
  };
  return <DeviceContext.Provider value={value}>{children}</DeviceContext.Provider>;
}
export function useDevices() {
  const c = useContext(DeviceContext);
  if (!c) throw new Error("DeviceProvider missing");
  return c;
}
