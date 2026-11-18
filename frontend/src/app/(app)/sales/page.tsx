import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/placeholder-page";
import { appRoutes } from "@/lib/navigation";

export const metadata: Metadata = { title: "Sales" };

export default function SalesPage() {
  return <PlaceholderPage route={appRoutes.sales} />;
}
