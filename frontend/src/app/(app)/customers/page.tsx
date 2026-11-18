import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/placeholder-page";
import { appRoutes } from "@/lib/navigation";

export const metadata: Metadata = { title: "Customers" };

export default function CustomersPage() {
  return <PlaceholderPage route={appRoutes.customers} />;
}
