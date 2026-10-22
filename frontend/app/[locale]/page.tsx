import { setRequestLocale } from "next-intl/server";
import { Landing } from "@/components/Landing";
import { getMe } from "@/lib/server";

export default async function Page({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const me = await getMe();
  return <Landing loggedIn={!!me} />;
}
