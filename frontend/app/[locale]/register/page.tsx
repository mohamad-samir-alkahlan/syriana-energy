import { setRequestLocale } from "next-intl/server";
import { RegisterForm } from "@/components/AuthForms";

export default async function Page({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return <RegisterForm />;
}
