import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/placeholder-page";
import { appRoutes } from "@/lib/navigation";

export const metadata: Metadata = { title: "Suppliers" };

export default function SuppliersPage() {
  return <PlaceholderPage route={appRoutes.suppliers} />;
}
