import { Suspense } from "react";
import { AppShell } from "@/components/shell/app-shell";
import { LoadingBlock } from "@/components/ui";

/** Authenticated area. The proxy redirects cookie-less visitors; AppShell verifies the
 *  session with the backend and handles password-change and shop-selection states.
 *  Suspense: on dynamic routes (e.g. /catalog/[productId]) the pathname AppShell reads is
 *  runtime data under cacheComponents, so the shell streams in after the static fallback. */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<LoadingBlock label="…" />}>
      <AppShell>{children}</AppShell>
    </Suspense>
  );
}
