import { setRequestLocale } from "next-intl/server";
import { VerifyEmail } from "@/components/AuthForms";

export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ token?: string | string[] }>;
}) {
  setRequestLocale((await params).locale);
  const tok = (await searchParams).token;
  return <VerifyEmail token={typeof tok === "string" ? tok : ""} />;
}
