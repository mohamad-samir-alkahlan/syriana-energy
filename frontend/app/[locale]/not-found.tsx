import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";

export default function NotFound() {
  const t = useTranslations("common");
  return (
    <main className="grid min-h-dvh place-items-center p-6 text-center">
      <div>
        <div className="text-6xl font-bold text-accent">404</div>
        <p className="mt-2 text-muted">{t("not_found")}</p>
        <Link href="/" className="mt-4 inline-block rounded-xl bg-accent px-5 py-2 text-on-accent">
          {t("home")}
        </Link>
      </div>
    </main>
  );
}
