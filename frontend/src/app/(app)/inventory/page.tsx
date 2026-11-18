import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/placeholder-page";
import { appRoutes } from "@/lib/navigation";

export const metadata: Metadata = { title: "Inventory" };

export default function InventoryPage() {
  return <PlaceholderPage route={appRoutes.inventory} />;
}
