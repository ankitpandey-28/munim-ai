import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/placeholder-page";
import { appRoutes } from "@/lib/navigation";

export const metadata: Metadata = { title: "Voice Assistant" };

export default function AssistantPage() {
  return <PlaceholderPage route={appRoutes.assistant} />;
}
