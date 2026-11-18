import type { Metadata } from "next";
import { Suspense } from "react";
import { ShopsView } from "@/components/shops-view";
import { LoadingBlock } from "@/components/ui";

export const metadata: Metadata = { title: "My shops" };

export default function ShopsPage() {
  return (
    <Suspense fallback={<LoadingBlock label="…" />}>
      <ShopsView />
    </Suspense>
  );
}
