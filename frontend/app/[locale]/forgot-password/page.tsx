import { setRequestLocale } from "next-intl/server";
import { ForgotPasswordForm } from "@/components/AuthForms";

export default async function Page({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return <ForgotPasswordForm />;
}
