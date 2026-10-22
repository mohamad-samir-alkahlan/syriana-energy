"use client";

import { useState, type FormEvent } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/navigation";
import { api, ApiError, type Locale } from "@/lib/api";
import { PoweredBy, PublicHeader } from "./Chrome";
import { Button, Card, Input, errorText } from "./ui";

function Shell({ title, sub, children, footer }: { title: string; sub?: string; children: React.ReactNode; footer: React.ReactNode }) {
  return (
    <div className="min-h-dvh">
      <PublicHeader />
      <main className="mx-auto grid max-w-md px-4 pb-10 pt-6 sm:pt-12">
        <Card className="rise !p-6 sm:!p-8">
          <h1 className="text-2xl font-bold">{title}</h1>
          {sub && <p className="mt-1 text-sm text-muted">{sub}</p>}
          <div className="mt-6">{children}</div>
        </Card>
        <p className="mt-5 text-center text-sm text-muted">{footer}</p>
        <PoweredBy className="mt-6" />
      </main>
    </div>
  );
}

export function LoginForm() {
  const t = useTranslations("auth");
  const locale = useLocale();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [needTotp, setNeedTotp] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      await api.login({ email: email.trim(), password, totp_code: needTotp ? code.trim() : undefined });
      router.replace("/app");
      router.refresh();
    } catch (x) {
      if (x instanceof ApiError && x.code === "totp_required") {
        setNeedTotp(true);
      } else {
        setErr(errorText(x, locale) || t("failed"));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Shell
      title={needTotp ? t("totp_title") : t("login_title")}
      sub={needTotp ? t("totp_sub") : t("login_sub")}
      footer={
        <>
          {t("no_account")}{" "}
          <Link href="/register" className="text-accent">
            {t("register")}
          </Link>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-4" noValidate>
        {!needTotp ? (
          <>
            <Input label={t("email")} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} dir="ltr" data-autofocus />
            <Input label={t("password")} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} dir="ltr" />
          </>
        ) : (
          <Input
            label={t("totp_code")}
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            pattern="[0-9]*"
            required
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            dir="ltr"
            className="text-center text-2xl tracking-[.5em]"
            autoFocus
          />
        )}
        {err && (
          <p role="alert" className="text-sm text-red">
            {err}
          </p>
        )}
        <Button type="submit" className="w-full" loading={busy} disabled={!email || !password || (needTotp && code.length < 6)}>
          {needTotp ? t("verify") : t("login")}
        </Button>
        {needTotp && (
          <button type="button" className="w-full text-center text-sm text-muted" onClick={() => { setNeedTotp(false); setCode(""); }}>
            {t("back")}
          </button>
        )}
      </form>
    </Shell>
  );
}

export function RegisterForm() {
  const t = useTranslations("auth");
  const locale = useLocale() as Locale;
  const router = useRouter();
  const [f, setF] = useState({ name: "", tenant_name: "", email: "", password: "" });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (f.password.length < 8) return setErr(t("password_short"));
    setBusy(true);
    setErr("");
    try {
      await api.register({ ...f, email: f.email.trim(), tenant_name: f.tenant_name.trim() || f.name.trim(), locale });
      router.replace("/app");
      router.refresh();
    } catch (x) {
      setErr(errorText(x, locale) || t("failed"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Shell
      title={t("register_title")}
      sub={t("register_sub")}
      footer={
        <>
          {t("have_account")}{" "}
          <Link href="/login" className="text-accent">
            {t("login")}
          </Link>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-4" noValidate>
        <Input label={t("name")} autoComplete="name" required value={f.name} onChange={set("name")} data-autofocus />
        <Input label={t("tenant_name")} hint={t("tenant_hint")} value={f.tenant_name} onChange={set("tenant_name")} />
        <Input label={t("email")} type="email" autoComplete="email" required value={f.email} onChange={set("email")} dir="ltr" />
        <Input label={t("password")} type="password" autoComplete="new-password" required value={f.password} onChange={set("password")} dir="ltr" hint={t("password_hint")} />
        {err && (
          <p role="alert" className="text-sm text-red">
            {err}
          </p>
        )}
        <Button type="submit" className="w-full" loading={busy} disabled={!f.name || !f.email || !f.password}>
          {t("register")}
        </Button>
      </form>
    </Shell>
  );
}
