"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
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
            <div className="-mt-2 text-end">
              <Link href="/forgot-password" className="text-xs text-accent">
                {t("forgot_link")}
              </Link>
            </div>
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

const backToLogin = (label: string) => (
  <Link href="/login" className="text-accent">
    {label}
  </Link>
);

export function ForgotPasswordForm() {
  const t = useTranslations("auth");
  const locale = useLocale() as Locale;
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      await api.forgotPassword(email.trim(), locale);
      setSent(true);
    } catch (x) {
      setErr(errorText(x, locale) || t("failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Shell title={t("forgot_title")} sub={sent ? undefined : t("forgot_sub")} footer={backToLogin(t("back_to_login"))}>
      {sent ? (
        <p role="status" className="text-sm">{t("forgot_sent")}</p>
      ) : (
        <form onSubmit={submit} className="space-y-4" noValidate>
          <Input label={t("email")} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} dir="ltr" data-autofocus />
          {err && <p role="alert" className="text-sm text-red">{err}</p>}
          <Button type="submit" className="w-full" loading={busy} disabled={!email}>
            {t("forgot_send")}
          </Button>
        </form>
      )}
    </Shell>
  );
}

export function ResetPasswordForm({ token }: { token: string }) {
  const t = useTranslations("auth");
  const locale = useLocale();
  const [password, setPassword] = useState("");
  const [done, setDone] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (password.length < 8) return setErr(t("password_short"));
    setBusy(true);
    setErr("");
    try {
      await api.resetPassword(token, password);
      setDone(true);
    } catch (x) {
      setErr(errorText(x, locale) || t("failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Shell title={t("reset_title")} footer={backToLogin(t("back_to_login"))}>
      {done ? (
        <p role="status" className="text-sm">{t("reset_done")}</p>
      ) : !token ? (
        <p role="alert" className="text-sm text-red">{t("link_invalid")}</p>
      ) : (
        <form onSubmit={submit} className="space-y-4" noValidate>
          <Input label={t("new_password")} type="password" autoComplete="new-password" required value={password} onChange={(e) => setPassword(e.target.value)} dir="ltr" hint={t("password_hint")} data-autofocus />
          {err && <p role="alert" className="text-sm text-red">{err}</p>}
          <Button type="submit" className="w-full" loading={busy} disabled={!password}>
            {t("reset_save")}
          </Button>
        </form>
      )}
    </Shell>
  );
}

export function VerifyEmail({ token }: { token: string }) {
  const t = useTranslations("auth");
  const locale = useLocale();
  const [state, setState] = useState<"busy" | "ok" | "bad">(token ? "busy" : "bad");
  const [err, setErr] = useState("");
  const once = useRef(false);

  useEffect(() => {
    if (!token || once.current) return;
    once.current = true;
    api.verifyEmail(token).then(
      () => setState("ok"),
      (x) => {
        setErr(errorText(x, locale) || t("link_invalid"));
        setState("bad");
      },
    );
  }, [token, locale, t]);

  return (
    <Shell title={t("verify_title")} footer={backToLogin(t("back_to_login"))}>
      {state === "busy" && <p role="status" className="text-sm text-muted">{t("verify_busy")}</p>}
      {state === "ok" && <p role="status" className="text-sm">{t("verify_done")}</p>}
      {state === "bad" && <p role="alert" className="text-sm text-red">{err || t("link_invalid")}</p>}
    </Shell>
  );
}
