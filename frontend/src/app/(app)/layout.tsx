import { AppShell } from "@/components/shell/app-shell";

/** Authenticated area. The proxy redirects cookie-less visitors; AppShell verifies the
 *  session with the backend and handles password-change and shop-selection states. */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
