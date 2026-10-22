import { Suspense } from "react";
import { Devices } from "@/components/Devices";

export default function Page() {
  return (
    <Suspense>
      <Devices />
    </Suspense>
  );
}
