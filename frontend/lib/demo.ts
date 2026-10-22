import { api, items } from "./api";

/** Create a site (if needed) and attach the simulated `demo` driver device. */
export async function addDemoDevice(siteName: string, deviceName: string) {
  const sites = items(await api.sites());
  const site = sites[0] ?? (await api.createSite({ name: siteName }));
  const found = await api.discover({ driver: "demo", credentials: {} });
  const d = found.devices[0];
  return api.createDevice({
    site_id: site.id,
    driver: "demo",
    integration_token: found.integration_token,
    external_id: d?.external_id ?? "demo-1",
    name: deviceName,
  });
}
