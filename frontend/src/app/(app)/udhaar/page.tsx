import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/placeholder-page";
import { appRoutes } from "@/lib/navigation";

export const metadata: Metadata = { title: "Udhaar" };

export default function UdhaarPage() {
  return <PlaceholderPage route={appRoutes.udhaar} />;
}
