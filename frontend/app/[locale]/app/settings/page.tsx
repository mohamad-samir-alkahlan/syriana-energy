import { Suspense } from "react";
import { Settings } from "@/components/Settings";

export default function Page() {
  return (
    <Suspense>
      <Settings />
    </Suspense>
  );
}
