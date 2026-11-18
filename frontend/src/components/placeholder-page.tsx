"use client";

import type { AppRoute } from "@/lib/navigation";
import { useI18n } from "@/lib/i18n/language-provider";
import { EmptyState } from "@/components/ui";

/** Placeholder shown on every route until its phase implements real functionality. */
export function PlaceholderPage({ route }: { route: AppRoute }) {
  const { t } = useI18n();
  return (
    <section className="mx-auto w-full max-w-3xl">
      <h1 className="text-2xl font-semibold tracking-tight">{t(route.labelKey)}</h1>
      <p className="mt-2 text-zinc-600 dark:text-zinc-400">{route.description}</p>
      <div className="mt-6">
        <EmptyState title={`${t("placeholder.phase")} ${route.phase}`} />
      </div>
    </section>
  );
}
