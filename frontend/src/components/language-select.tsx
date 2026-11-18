"use client";

import { LANGUAGES, type UiLanguage } from "@/lib/i18n/dictionaries";
import { useI18n } from "@/lib/i18n/language-provider";

export function LanguageSelect({ compact = false }: { compact?: boolean }) {
  const { language, setLanguage, t } = useI18n();
  return (
    <label className="flex items-center gap-2 text-sm">
      <span className={compact ? "sr-only" : ""}>{t("common.language")}</span>
      <select
        value={language}
        onChange={(e) => setLanguage(e.target.value as UiLanguage)}
        className="min-h-10 rounded-lg border border-zinc-300 bg-white px-2 dark:border-zinc-700 dark:bg-zinc-900"
      >
        {LANGUAGES.map((l) => (
          <option key={l.code} value={l.code}>
            {l.label}
          </option>
        ))}
      </select>
    </label>
  );
}
