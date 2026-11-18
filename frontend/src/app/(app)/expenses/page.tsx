import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/placeholder-page";
import { appRoutes } from "@/lib/navigation";

export const metadata: Metadata = { title: "Expenses" };

export default function ExpensesPage() {
  return <PlaceholderPage route={appRoutes.expenses} />;
}
