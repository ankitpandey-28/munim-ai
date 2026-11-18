"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useSyncExternalStore } from "react";
import { LANGUAGES, translate, type MessageKey, type UiLanguage } from "./dictionaries";

const STORAGE_KEY = "munim.language";
const CHANGE_EVENT = "munim-language-change";
const DEFAULT_LANGUAGE: UiLanguage = "hinglish";

interface LanguageContextValue {
  language: UiLanguage;
  setLanguage: (language: UiLanguage) => void;
  t: (key: MessageKey) => string;
}

const LanguageContext = createContext<LanguageContextValue | null>(null);

function isUiLanguage(value: unknown): value is UiLanguage {
  return LANGUAGES.some((l) => l.code === value);
}

function readStoredLanguage(): UiLanguage {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    return isUiLanguage(saved) ? saved : DEFAULT_LANGUAGE;
  } catch {
    return DEFAULT_LANGUAGE; // storage unavailable (private mode)
  }
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("storage", onChange);
  window.addEventListener(CHANGE_EVENT, onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(CHANGE_EVENT, onChange);
  };
}

/** Language preference stored per browser (a convenience, not account data). The server
 *  snapshot is the default so server and first client render match (no hydration mismatch). */
export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const language = useSyncExternalStore(subscribe, readStoredLanguage, () => DEFAULT_LANGUAGE);

  useEffect(() => {
    document.documentElement.lang = language === "hi" ? "hi" : "en";
  }, [language]);

  const setLanguage = useCallback((next: UiLanguage) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // ignore: preference simply isn't remembered
    }
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }, []);

  const value = useMemo<LanguageContextValue>(
    () => ({ language, setLanguage, t: (key) => translate(language, key) }),
    [language, setLanguage],
  );
  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useI18n(): LanguageContextValue {
  const ctx = useContext(LanguageContext);
  if (!ctx) throw new Error("useI18n must be used inside <LanguageProvider>");
  return ctx;
}
