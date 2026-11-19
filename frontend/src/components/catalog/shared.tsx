"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { type Category, type CatalogPermissions, type Unit, catalogPermissions, displayName } from "@/lib/catalog";
import { errorMessage } from "@/lib/errors";
import { useI18n } from "@/lib/i18n/language-provider";
import { useSession } from "@/lib/session";

/** Catalogue permissions for the active shop, from the backend-verified session. UI hints only. */
export function useCatalogPermissions(): CatalogPermissions {
  const { me } = useSession();
  const role = me?.memberships.find((m) => m.shop_id === me.active_shop_id)?.role;
  return catalogPermissions(role);
}

/** Units are global reference data: fetched once per page load and shared. */
let unitsPromise: Promise<Unit[]> | null = null;
function fetchUnits(): Promise<Unit[]> {
  unitsPromise ??= apiFetch<{ items: Unit[] }>("/catalog/units").then(
    (r) => r.items,
    (err) => {
      unitsPromise = null; // allow a retry after a failure
      throw err;
    },
  );
  return unitsPromise;
}

export function useUnits() {
  const { t } = useI18n();
  const [units, setUnits] = useState<Unit[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    fetchUnits().then(
      (u) => active && setUnits(u),
      (err) => active && setError(errorMessage(err, t)),
    );
    return () => {
      active = false;
    };
  }, [t]);
  return { units, error };
}

export function useCategories(includeArchived = false) {
  const { t } = useI18n();
  const [categories, setCategories] = useState<Category[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  useEffect(() => {
    let active = true;
    apiFetch<{ items: Category[] }>(`/catalog/categories${includeArchived ? "?include_archived=true" : ""}`).then(
      (r) => {
        if (!active) return;
        setCategories(r.items);
        setError(null);
      },
      (err) => active && setError(errorMessage(err, t)),
    );
    return () => {
      active = false;
    };
  }, [includeArchived, reloadToken, t]);
  const reload = useCallback(() => setReloadToken((n) => n + 1), []);
  return { categories, error, reload };
}

export function unitLabel(unit: Unit | undefined, code: string, language: string): string {
  if (!unit) return code;
  const name = language === "hi" ? unit.name_hi : unit.name_en;
  return name.toLowerCase() === unit.code ? unit.code : `${name} (${unit.code})`;
}

export function categoryName(categories: Category[] | null, id: string | null, language: string, fallback: string): string {
  if (!id) return fallback;
  const c = categories?.find((x) => x.id === id);
  return c ? displayName(c, language) : "…";
}

export function CatalogHeader() {
  const { t } = useI18n();
  const pathname = usePathname();
  const tabs = [
    { href: "/catalog", label: t("catalog.tab.products"), active: pathname === "/catalog" || /^\/catalog\/(?!categories)/.test(pathname) },
    { href: "/catalog/categories", label: t("catalog.tab.categories"), active: pathname.startsWith("/catalog/categories") },
  ];
  return (
    <div className="flex flex-col gap-3">
      <h1 className="text-2xl font-semibold tracking-tight">{t("catalog.title")}</h1>
      <nav aria-label={t("catalog.title")} className="flex gap-1 border-b border-zinc-200 dark:border-zinc-800">
        {tabs.map((tab) => (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={tab.active ? "page" : undefined}
            className={`-mb-px min-h-12 border-b-2 px-4 py-3 text-sm font-medium ${
              tab.active ? "border-emerald-700 text-emerald-900 dark:text-emerald-200" : "border-transparent text-zinc-600 hover:text-zinc-900 dark:text-zinc-400"
            }`}
          >
            {tab.label}
          </Link>
        ))}
      </nav>
    </div>
  );
}

export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(date);
}
