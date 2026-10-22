"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import { api, ApiError, items, type Customer, type Locale } from "@/lib/api";
import { canWrite, resetCache, useApi, useMe } from "@/lib/hooks";
import { fmtDate } from "@/lib/format";
import { useToast } from "./Providers";
import { Badge, Button, Card, ConfirmModal, Dot, EmptyState, ErrorState, Input, Modal, PageHeader, Skeleton, Upsell, errorText } from "./ui";
import { Icon } from "./Icon";

export function CustomersPage() {
  const t = useTranslations("customers");
  const locale = useLocale() as Locale;
  const { me, setMe } = useMe();
  const toast = useToast();
  const router = useRouter();
  const writable = canWrite(me);
  const { data, error, isLoading, mutate } = useApi(`customers:${me.tenant.id}`, () => api.customers());
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: "", owner_name: "", owner_email: "", password: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [del, setDel] = useState<Customer | null>(null);
  const list = items(data);

  if (error instanceof ApiError && error.code === "feature_not_in_plan")
    return (
      <>
        <PageHeader eyebrow={t("eyebrow")} title={t("title")} />
        <Upsell feature="customers" />
      </>
    );

  const create = async () => {
    setBusy(true);
    setErr("");
    try {
      await api.createCustomer({ name: f.name.trim(), owner_name: f.owner_name.trim(), owner_email: f.owner_email.trim(), password: f.password || undefined });
      setOpen(false);
      setF({ name: "", owner_name: "", owner_email: "", password: "" });
      await mutate();
      toast(t("created"));
    } catch (e) {
      setErr(errorText(e, locale));
    } finally {
      setBusy(false);
    }
  };
  const openCustomer = async (c: Customer) => {
    try {
      // the contract's /customers returns the customer (child tenant) id
      setMe(await api.switchTenant(c.id));
      await resetCache();
      router.push("/app");
      router.refresh();
    } catch (e) {
      toast(errorText(e, locale), "err");
    }
  };

  return (
    <div className="rise">
      <PageHeader eyebrow={t("eyebrow")} title={t("title")} sub={t("sub")} actions={writable && <Button icon="plus" onClick={() => setOpen(true)}>{t("add")}</Button>} />
      {isLoading && <Skeleton className="h-48 w-full" />}
      {error && <ErrorState error={error} onRetry={() => mutate()} />}
      {!isLoading && !error && list.length === 0 && (
        <EmptyState icon="users" title={t("empty")} text={t("empty_text")} action={writable && <Button icon="plus" onClick={() => setOpen(true)}>{t("add")}</Button>} />
      )}
      {list.length > 0 && (
        <>
          <div className="hidden overflow-hidden rounded-[18px] border border-line bg-panel md:block">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted">
                <tr>
                  {["name", "devices", "status", "plan", "created", ""].map((h) => (
                    <th key={h} className="px-4 py-3 text-start font-normal">{h && t(`col_${h}`)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {list.map((c) => (
                  <tr key={c.id} className="border-t border-line">
                    <td className="px-4 py-3 font-medium">{c.name}</td>
                    <td className="px-4 py-3"><span dir="ltr" className="num">{c.devices}</span></td>
                    <td className="px-4 py-3"><OnlineCell c={c} /></td>
                    <td className="px-4 py-3"><Badge>{c.plan}</Badge></td>
                    <td className="px-4 py-3 text-muted">{fmtDate(c.created_at, locale)}</td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-2">
                        <Button size="sm" icon="external" onClick={() => openCustomer(c)}>{t("open")}</Button>
                        {writable && <Button size="sm" variant="danger" aria-label={t("delete")} onClick={() => setDel(c)}><Icon name="trash" size={15} /></Button>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="space-y-3 md:hidden">
            {list.map((c) => (
              <Card key={c.id}>
                <div className="flex items-start justify-between gap-2">
                  <div className="font-semibold">{c.name}</div>
                  <Badge>{c.plan}</Badge>
                </div>
                <div className="mt-2 flex items-center justify-between text-sm text-muted">
                  <span><span dir="ltr" className="num">{c.devices}</span> {t("col_devices")}</span>
                  <OnlineCell c={c} />
                </div>
                <div className="mt-3 flex gap-2">
                  <Button size="sm" icon="external" className="flex-1" onClick={() => openCustomer(c)}>{t("open")}</Button>
                  {writable && <Button size="sm" variant="danger" aria-label={t("delete")} onClick={() => setDel(c)}><Icon name="trash" size={15} /></Button>}
                </div>
              </Card>
            ))}
          </div>
        </>
      )}

      <Modal open={open} onClose={() => setOpen(false)} title={t("add")} footer={<><Button variant="ghost" className="flex-1" onClick={() => setOpen(false)}>{t("cancel")}</Button><Button className="flex-1" loading={busy} disabled={!f.name.trim() || !f.owner_name.trim() || !f.owner_email.trim()} onClick={create}>{t("create")}</Button></>}>
        <div className="space-y-3">
          <Input label={t("f_name")} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} data-autofocus />
          <Input label={t("f_owner_name")} value={f.owner_name} onChange={(e) => setF({ ...f, owner_name: e.target.value })} />
          <Input label={t("f_owner_email")} type="email" dir="ltr" value={f.owner_email} onChange={(e) => setF({ ...f, owner_email: e.target.value })} />
          <Input label={t("f_password")} hint={t("f_password_hint")} type="password" dir="ltr" autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
          {err && <p role="alert" className="text-sm text-red">{err}</p>}
        </div>
      </Modal>
      <ConfirmModal
        open={!!del}
        danger
        title={t("delete_title")}
        text={t("delete_text", { name: del?.name ?? "" })}
        confirmLabel={t("delete")}
        onClose={() => setDel(null)}
        onConfirm={async () => {
          if (!del) return;
          try {
            await api.deleteCustomer(del.id);
            await mutate();
          } catch (e) {
            toast(errorText(e, locale), "err");
          }
          setDel(null);
        }}
      />
    </div>
  );
}

function OnlineCell({ c }: { c: Customer }) {
  const t = useTranslations("customers");
  if (c.devices === 0) return <span className="text-muted">—</span>;
  return (
    <span className="inline-flex items-center gap-2 text-sm">
      <Dot on={c.online > 0} pulse={false} />
      <span dir="ltr" className="num">{c.online}/{c.devices}</span> {t("online")}
    </span>
  );
}
