"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useLocale, useTranslations } from "next-intl";
import { api, ApiError, type ChatMessage } from "@/lib/api";
import { useDevices } from "@/lib/hooks";
import { DevicePicker } from "./DevicePicker";
import { Icon } from "./Icon";
import { Button, PageHeader, Spinner, Upsell, cx } from "./ui";

interface Msg extends ChatMessage {
  tools?: string[];
  error?: boolean;
}

export function Assistant() {
  const t = useTranslations("assistant");
  const locale = useLocale();
  const { selectedId } = useDevices();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const [noPlan, setNoPlan] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const chips = ["summary", "washer", "health", "tonight"] as const;

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [msgs, busy]);

  const send = async (content: string) => {
    const c = content.trim();
    if (!c || busy) return;
    const next: Msg[] = [...msgs, { role: "user", content: c }];
    setMsgs(next);
    setText("");
    setBusy(true);
    try {
      const r = await api.chat({ messages: next.filter((m) => !m.error).map(({ role, content }) => ({ role, content })), device_id: selectedId ?? undefined });
      setMsgs([...next, { role: "assistant", content: r.reply, tools: r.used_tools }]);
    } catch (e) {
      if (e instanceof ApiError && e.code === "ai_unavailable") {
        setUnavailable(true);
        setMsgs([...next, { role: "assistant", content: t("unavailable_msg"), error: true }]);
      } else if (e instanceof ApiError && e.code === "feature_not_in_plan") {
        setNoPlan(true);
      } else {
        setMsgs([...next, { role: "assistant", content: e instanceof ApiError ? e.text(locale) : t("error"), error: true }]);
      }
    } finally {
      setBusy(false);
    }
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    send(text);
  };

  if (noPlan)
    return (
      <>
        <PageHeader eyebrow={t("eyebrow")} title={t("title")} />
        <Upsell feature="ai" />
      </>
    );

  return (
    <div className="rise">
      <PageHeader eyebrow={t("eyebrow")} title={t("title")} sub={t("sub")} actions={<DevicePicker />} />
      {unavailable && (
        <div role="status" className="mb-3 flex items-start gap-2 rounded-xl border border-[color-mix(in_srgb,var(--gold)_45%,transparent)] bg-[color-mix(in_srgb,var(--gold)_10%,transparent)] px-4 py-3 text-sm text-gold">
          <Icon name="info" size={17} className="mt-0.5 shrink-0" />
          {t("unavailable_banner")}
        </div>
      )}
      <div className="flex h-[calc(100dvh-250px)] min-h-[420px] flex-col rounded-[18px] border border-line bg-panel">
        <div className="flex-1 space-y-2.5 overflow-y-auto p-4" aria-live="polite">
          {msgs.length === 0 && (
            <div className="grid h-full place-items-center text-center">
              <div>
                <div className="mx-auto mb-3 grid h-14 w-14 place-items-center rounded-2xl bg-[color-mix(in_srgb,var(--accent)_15%,transparent)] text-accent">
                  <Icon name="chat" size={26} />
                </div>
                <p className="max-w-sm text-sm text-muted">{t("welcome")}</p>
              </div>
            </div>
          )}
          {msgs.map((m, i) => (
            <div key={i} className={cx("flex", m.role === "user" ? "justify-start" : "justify-end")}>
              <div
                className={cx(
                  "max-w-[88%] whitespace-pre-wrap rounded-2xl border px-3.5 py-2.5 text-sm leading-relaxed sm:max-w-[75%]",
                  m.role === "user"
                    ? "border-[color-mix(in_srgb,var(--accent)_30%,transparent)] bg-[color-mix(in_srgb,var(--accent)_15%,transparent)]"
                    : m.error
                      ? "border-[color-mix(in_srgb,var(--gold)_45%,transparent)] bg-[color-mix(in_srgb,var(--gold)_8%,transparent)] text-gold"
                      : "border-line bg-panel-hi",
                )}
              >
                {m.content}
                {!!m.tools?.length && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {m.tools.map((x) => (
                      <span key={x} dir="ltr" className="rounded-full border border-line px-2 py-0.5 text-[10px] text-muted">
                        {x}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          {busy && (
            <div className="flex justify-end">
              <div className="flex items-center gap-2 rounded-2xl border border-line bg-panel-hi px-3.5 py-2.5 text-sm text-muted">
                <Spinner /> {t("thinking")}
              </div>
            </div>
          )}
          <div ref={end} />
        </div>
        <div className="border-t border-line p-3">
          <div className="mb-2 flex flex-wrap gap-1.5">
            {chips.map((c) => (
              <button key={c} onClick={() => send(t(`chip_${c}`))} disabled={busy} className="rounded-full border border-line bg-panel px-3 py-1 text-xs text-muted transition hover:border-accent hover:text-fg disabled:opacity-50">
                {t(`chip_${c}`)}
              </button>
            ))}
          </div>
          <form onSubmit={submit} className="flex gap-2">
            <textarea
              rows={1}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  send(text);
                }
              }}
              placeholder={t("placeholder")}
              aria-label={t("placeholder")}
              className="max-h-32 min-h-[44px] flex-1 resize-none rounded-[10px] border border-line bg-bg2 px-3 py-2.5 text-sm focus:border-accent focus:outline-none"
            />
            <Button type="submit" disabled={!text.trim() || busy} aria-label={t("send")}>
              <Icon name="send" size={17} className="rtl:-scale-x-100" />
              <span className="hidden sm:inline">{t("send")}</span>
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
