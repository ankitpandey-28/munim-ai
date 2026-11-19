"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Alert, Badge, Button, Card, CheckboxField, EmptyState, LoadingBlock, SelectField, TextField } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { type Product, type ProductPage, displayName, formatPaise, formatQuantity, productQuery } from "@/lib/catalog";
import { errorMessage } from "@/lib/errors";
import { useI18n } from "@/lib/i18n/language-provider";
import { ProductForm } from "./product-form";
import { CatalogHeader, categoryName, unitLabel, useCatalogPermissions, useCategories, useUnits } from "./shared";

export function ProductsView() {
  const { t, language } = useI18n();
  const perms = useCatalogPermissions();
  const { units, error: unitsError } = useUnits();
  const { categories, error: categoriesError } = useCategories(true);

  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [page, setPage] = useState<{ items: Product[]; total: number } | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  // Debounce typing so each keystroke doesn't hit the API.
  useEffect(() => {
    const id = setTimeout(() => setQuery(search), 300);
    return () => clearTimeout(id);
  }, [search]);

  useEffect(() => {
    const controller = new AbortController();
    apiFetch<ProductPage>(`/catalog/products?${productQuery({ q: query, categoryId, includeArchived })}`, { signal: controller.signal }).then(
      (r) => {
        setPage({ items: r.items, total: r.total });
        setError(null);
      },
      (err) => {
        if ((err as Error)?.name !== "AbortError") setError(errorMessage(err, t));
      },
    );
    return () => controller.abort();
  }, [query, categoryId, includeArchived, reloadToken, t]);

  async function loadMore() {
    if (!page) return;
    setLoadingMore(true);
    try {
      const r = await apiFetch<ProductPage>(`/catalog/products?${productQuery({ q: query, categoryId, includeArchived, offset: page.items.length })}`);
      setPage({ items: [...page.items, ...r.items], total: r.total });
    } catch (err) {
      setError(errorMessage(err, t));
    } finally {
      setLoadingMore(false);
    }
  }

  const filtering = Boolean(query.trim() || categoryId);
  const activeCategories = (categories ?? []).filter((c) => !c.archived_at);

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-5">
      <CatalogHeader />
      {(unitsError || categoriesError) && <Alert>{unitsError || categoriesError}</Alert>}
      {!perms.manage && <Alert kind="info">{t("catalog.viewOnly")}</Alert>}

      {perms.manage && !adding && (
        <div>
          <Button onClick={() => setAdding(true)} disabled={!units || !categories}>
            + {t("catalog.addProduct")}
          </Button>
        </div>
      )}
      {perms.manage && adding && units && categories && (
        <Card title={t("catalog.addProduct")}>
          <ProductForm
            product={null}
            units={units}
            categories={categories}
            showCost={perms.viewCosts}
            onSaved={() => setReloadToken((n) => n + 1)}
            onCancel={() => setAdding(false)}
          />
        </Card>
      )}

      <div className="grid gap-3 sm:grid-cols-[1fr_14rem]">
        <TextField label={t("catalog.search")} type="search" value={search} onChange={(e) => setSearch(e.target.value)} maxLength={120} autoComplete="off" />
        <SelectField
          label={t("catalog.field.category")}
          value={categoryId}
          onChange={(e) => setCategoryId(e.target.value)}
          options={[{ value: "", label: t("catalog.allCategories") }, ...activeCategories.map((c) => ({ value: c.id, label: displayName(c, language) }))]}
        />
      </div>
      <CheckboxField label={t("catalog.includeArchived")} checked={includeArchived} onChange={(e) => setIncludeArchived(e.target.checked)} />

      {error && <Alert>{error}</Alert>}
      {!page && !error && <LoadingBlock label={t("common.loading")} />}
      {page && page.items.length === 0 && (
        <EmptyState title={filtering ? t("catalog.noResults") : t("catalog.empty")} description={filtering ? undefined : t("catalog.emptyHelp")} />
      )}
      {page && page.items.length > 0 && (
        <>
          <p className="text-sm text-zinc-500" aria-live="polite">
            {page.total} {t("catalog.count")}
          </p>
          <ul className="flex flex-col gap-2" data-testid="product-list">
            {page.items.map((p) => {
              const unit = units?.find((u) => u.code === p.base_unit_code);
              return (
                <li key={p.id}>
                  <Link
                    href={`/catalog/${p.id}`}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-zinc-200 p-3 hover:bg-zinc-50 dark:border-zinc-800 dark:hover:bg-zinc-900"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="flex flex-wrap items-center gap-2 font-medium">
                        <span className="truncate">{displayName(p, language)}</span>
                        {p.is_loose ? <Badge>{t("catalog.loose")}</Badge> : null}
                        {!p.track_stock ? <Badge>{t("catalog.untracked")}</Badge> : null}
                        {p.archived_at ? <Badge tone="warn">{t("catalog.archived")}</Badge> : null}
                      </p>
                      <p className="text-xs text-zinc-500">
                        {categoryName(categories, p.category_id, language, t("catalog.noCategory"))}
                        {p.barcode ? ` · ${p.barcode}` : ""}
                        {p.reorder_level ? ` · ${t("catalog.field.reorderLevel")}: ${formatQuantity(p.reorder_level)} ${p.base_unit_code}` : ""}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="font-semibold">
                        {formatPaise(p.selling_price_paise)}
                        <span className="text-xs font-normal text-zinc-500">
                          {" "}
                          / {unitLabel(unit, p.base_unit_code, language)}
                        </span>
                      </p>
                      {p.costs_visible && p.default_cost_price_paise != null && (
                        <p className="text-xs text-zinc-500">
                          {t("catalog.priceType.cost")}: {formatPaise(p.default_cost_price_paise)}
                        </p>
                      )}
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
          {page.items.length < page.total && (
            <Button variant="secondary" onClick={() => void loadMore()} loading={loadingMore}>
              {t("common.loadMore")}
            </Button>
          )}
        </>
      )}
    </div>
  );
}
