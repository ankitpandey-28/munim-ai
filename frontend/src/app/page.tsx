"use client";

import Link from "next/link";
import { LanguageSelect } from "@/components/language-select";
import { useI18n } from "@/lib/i18n/language-provider";

export default function HomePage() {
  const { t } = useI18n();
  return (
    <main className="flex flex-1 flex-col items-center justify-center px-4 py-16 text-center">
      <div className="absolute right-4 top-4">
        <LanguageSelect compact />
      </div>
      <p className="text-sm font-medium text-emerald-700 dark:text-emerald-400">{t("app.tagline")}</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">{t("app.name")}</h1>
      <p className="mt-3 max-w-md text-zinc-600 dark:text-zinc-400">{t("app.subtitle")}</p>
      <div className="mt-8 flex w-full max-w-xs flex-col gap-3 sm:max-w-none sm:flex-row sm:justify-center">
        <Link
          href="/login"
          className="flex min-h-12 items-center justify-center rounded-lg bg-emerald-700 px-6 py-3 font-medium text-white hover:bg-emerald-800"
        >
          {t("auth.login")}
        </Link>
        <Link
          href="/register"
          className="flex min-h-12 items-center justify-center rounded-lg border border-zinc-300 px-6 py-3 font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900"
        >
          {t("auth.register")}
        </Link>
      </div>
    </main>
  );
}
