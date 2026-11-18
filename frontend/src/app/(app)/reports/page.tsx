import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/placeholder-page";
import { appRoutes } from "@/lib/navigation";

export const metadata: Metadata = { title: "Reports" };

export default function ReportsPage() {
  return <PlaceholderPage route={appRoutes.reports} />;
}
