"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Badge, Button, Card, ConfirmAction, EmptyState, LoadingBlock, SelectField, TextField } from "@/components/ui";
import { ApiError, apiFetch, newIdempotencyKey } from "@/lib/api";
import {
  type CatalogPermissions,
  type PricePage,
  type PriceRecord,
  type Product,
  type ProductAlias,
  displayName,
  formatPaise,
  formatQuantity,
  paiseToRupeeInput,
  parseRupeesToPaise,
} from "@/lib/catalog";
import { errorMessage, formErrors } from "@/lib/errors";
import { useI18n } from "@/lib/i18n/language-provider";
import type { Language } from "@/lib/types";
import { ProductForm, amountError } from "./product-form";
import { CatalogHeader, categoryName, formatDateTime, unitLabel, useCatalogPermissions, useCategories, useUnits } from "./shared";

const HISTORY_PAGE = 20;

export function ProductDetail() {
  const { productId } = useParams<{ productId: string }>();
  const { t, language } = useI18n();
  const perms = useCatalogPermissions();
  const { units } = useUnits();
  const { categories } = useCategories(true);
  const [product, setProduct] = useState<Product | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [historyToken, setHistoryToken] = useState(0);

  const load = useCallback(() => {
    apiFetch<Product>(`/catalog/products/${encodeURIComponent(productId)}`).then(
      (p) => {
        setProduct(p);
        setError(null);
      },
      (err) => setError(errorMessage(err, t)),
    );
  }, [productId, t]);
  useEffect(load, [load]);

  if (error && !product) {
    return (
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
        <CatalogHeader />
        <Alert>{error}</Alert>
        <BackLink />
      </div>
    );
  }
  if (!product || !units || !categories) return <LoadingBlock label={t("common.loading")} />;

  const archived = Boolean(product.archived_at);
  const canManage = perms.manage && !archived;
  const unit = units.find((u) => u.code === product.base_unit_code);
  const updated = (p: Product) => {
    setProduct(p);
    setHistoryToken((n) => n + 1);
  };

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-5">
      <CatalogHeader />
      <BackLink />
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-xl font-semibold">{displayName(product, language)}</h2>
        {product.is_loose ? <Badge>{t("catalog.loose")}</Badge> : <Badge>{t("catalog.packaged")}</Badge>}
        {!product.track_stock && <Badge>{t("catalog.untracked")}</Badge>}
        {archived && <Badge tone="warn">{t("catalog.archived")}</Badge>}
      </div>
      {archived && <Alert kind="info">{t("catalog.archivedNotice")}</Alert>}
      {!perms.manage && <Alert kind="info">{t("catalog.viewOnly")}</Alert>}

      <Card
        title={t("catalog.details")}
        action={
          canManage && !editing ? (
            <Button variant="secondary" onClick={() => setEditing(true)} className="min-h-10">
              {t("common.edit")}
            </Button>
          ) : undefined
        }
      >
        {editing && canManage ? (
          <ProductForm
            key={product.version}
            product={product}
            units={units}
            categories={categories}
            showCost={perms.viewCosts}
            onSaved={(p) => {
              updated(p);
              setEditing(false);
            }}
            onConflict={load}
            onCancel={() => setEditing(false)}
          />
        ) : (
          <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
            <Detail label={t("catalog.field.name")} value={product.name} />
            <Detail label={t("catalog.field.nameHi")} value={product.name_hi ?? "—"} />
            <Detail label={t("catalog.field.category")} value={categoryName(categories, product.category_id, language, t("catalog.noCategory"))} />
            <Detail label={t("catalog.field.unit")} value={unitLabel(unit, product.base_unit_code, language)} />
            <Detail label={t("catalog.field.reorderLevel")} value={product.reorder_level ? `${formatQuantity(product.reorder_level)} ${product.base_unit_code}` : "—"} />
            <Detail label={t("catalog.field.barcode")} value={product.barcode ?? "—"} />
            <Detail label={t("catalog.field.trackStock")} value={t(product.track_stock ? "common.yes" : "common.no")} />
          </dl>
        )}
      </Card>

      <PricesCard product={product} perms={perms} canManage={canManage} unitText={unitLabel(unit, product.base_unit_code, language)} onUpdated={updated} onConflict={load} />
      <PriceHistoryCard productId={product.id} showCost={perms.viewCosts} reloadToken={historyToken} />
      <AliasesCard product={product} canManage={canManage} />

      {canManage && (
        <ArchiveProduct product={product} onArchived={updated} />
      )}
    </div>
  );
}

function BackLink() {
  const { t } = useI18n();
  return (
    <Link href="/catalog" className="inline-flex min-h-10 w-fit items-center text-sm font-medium text-emerald-800 hover:underline dark:text-emerald-300">
      ← {t("catalog.back")}
    </Link>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-zinc-500">{label}</dt>
      <dd className="font-medium break-words">{value}</dd>
    </div>
  );
}

function PricesCard({
  product,
  perms,
  canManage,
  unitText,
  onUpdated,
  onConflict,
}: {
  product: Product;
  perms: CatalogPermissions;
  canManage: boolean;
  unitText: string;
  onUpdated: (p: Product) => void;
  onConflict: () => void;
}) {
  const { t } = useI18n();
  const canChange = canManage && perms.managePrices;
  const showCost = perms.viewCosts && product.costs_visible;
  const [open, setOpen] = useState(false);
  const [selling, setSelling] = useState(paiseToRupeeInput(product.selling_price_paise));
  const [cost, setCost] = useState(paiseToRupeeInput(product.default_cost_price_paise));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [pending, setPending] = useState<Record<string, number> | null>(null);
  const [message, setMessage] = useState<{ kind: "error" | "success" | "info"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const key = useRef(newIdempotencyKey());

  function review(event: React.FormEvent) {
    event.preventDefault();
    setMessage(null);
    const next: Record<string, string> = {};
    const changes: Record<string, number> = {};
    const s = parseRupeesToPaise(selling);
    if (!s.ok) next.selling = t(amountError(s.error));
    else if (s.value !== product.selling_price_paise) changes.selling_price_paise = s.value as number;
    if (showCost) {
      const c = parseRupeesToPaise(cost, { required: product.default_cost_price_paise !== null });
      if (!c.ok) next.cost = t(amountError(c.error));
      else if (c.value !== null && c.value !== product.default_cost_price_paise) changes.default_cost_price_paise = c.value;
    }
    setErrors(next);
    if (Object.keys(next).length) return;
    if (Object.keys(changes).length === 0) {
      setMessage({ kind: "info", text: t("catalog.noChanges") });
      return;
    }
    setPending(changes); // show the confirmation step before anything is sent
  }

  async function confirm() {
    if (!pending) return;
    setSaving(true);
    try {
      const updated = await apiFetch<Product>(`/catalog/products/${product.id}/prices`, {
        method: "POST",
        idempotencyKey: key.current,
        body: { version: product.version, ...pending },
      });
      key.current = newIdempotencyKey();
      setPending(null);
      setOpen(false);
      setMessage({ kind: "success", text: t("catalog.priceUpdated") });
      onUpdated(updated);
    } catch (err) {
      if (err instanceof ApiError && err.status >= 400 && err.status < 500) key.current = newIdempotencyKey();
      setPending(null);
      if (err instanceof ApiError && err.code === "VERSION_CONFLICT") {
        setMessage({ kind: "info", text: t("catalog.versionConflict") });
        onConflict();
      } else {
        setErrors(formErrors(err, t));
        setMessage({ kind: "error", text: errorMessage(err, t) });
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card
      title={t("catalog.prices")}
      action={
        canChange && !open ? (
          <Button
            variant="secondary"
            className="min-h-10"
            onClick={() => {
              setSelling(paiseToRupeeInput(product.selling_price_paise));
              setCost(paiseToRupeeInput(product.default_cost_price_paise));
              setErrors({});
              setMessage(null);
              setOpen(true);
            }}
          >
            {t("catalog.updatePrices")}
          </Button>
        ) : undefined
      }
    >
      <div className="flex flex-col gap-4">
        {message && <Alert kind={message.kind}>{message.text}</Alert>}
        <dl className="grid gap-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-zinc-500">{t("catalog.field.sellingPrice")}</dt>
            <dd className="text-lg font-semibold" data-testid="selling-price">
              {formatPaise(product.selling_price_paise)} <span className="text-sm font-normal text-zinc-500">/ {unitText}</span>
            </dd>
          </div>
          {showCost && (
            <div>
              <dt className="text-zinc-500">{t("catalog.field.costPrice")}</dt>
              <dd className="text-lg font-semibold" data-testid="cost-price">
                {formatPaise(product.default_cost_price_paise)}
              </dd>
            </div>
          )}
        </dl>
        {open && canChange && (
          <form onSubmit={review} noValidate className="flex flex-col gap-4 border-t border-zinc-200 pt-4 dark:border-zinc-800">
            <div className="grid gap-4 sm:grid-cols-2">
              <TextField label={t("catalog.field.sellingPrice")} hint={t("catalog.field.priceHint")} inputMode="decimal" value={selling} onChange={(e) => { setSelling(e.target.value); setPending(null); }} error={errors.selling ?? errors.selling_price_paise} autoComplete="off" />
              {showCost && (
                <TextField label={t("catalog.field.costPrice")} hint={t("catalog.field.costPriceHint")} inputMode="decimal" value={cost} onChange={(e) => { setCost(e.target.value); setPending(null); }} error={errors.cost ?? errors.default_cost_price_paise} autoComplete="off" />
              )}
            </div>
            {pending ? (
              <div role="group" className="flex flex-col gap-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-100">
                <p className="font-medium">{t("catalog.priceConfirm")}</p>
                <ul className="list-inside list-disc">
                  {pending.selling_price_paise !== undefined && (
                    <li>
                      {t("catalog.priceType.selling")}: {formatPaise(product.selling_price_paise)} → <strong>{formatPaise(pending.selling_price_paise)}</strong>
                    </li>
                  )}
                  {pending.default_cost_price_paise !== undefined && (
                    <li>
                      {t("catalog.priceType.cost")}: {formatPaise(product.default_cost_price_paise)} → <strong>{formatPaise(pending.default_cost_price_paise)}</strong>
                    </li>
                  )}
                </ul>
                <div className="flex flex-wrap gap-2">
                  <Button type="button" loading={saving} onClick={() => void confirm()}>
                    {t("common.confirm")}
                  </Button>
                  <Button type="button" variant="secondary" disabled={saving} onClick={() => setPending(null)}>
                    {t("common.cancel")}
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex flex-wrap gap-2">
                <Button type="submit">{t("catalog.updatePrices")}</Button>
                <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
                  {t("common.cancel")}
                </Button>
              </div>
            )}
          </form>
        )}
      </div>
    </Card>
  );
}

function PriceHistoryCard({ productId, showCost, reloadToken }: { productId: string; showCost: boolean; reloadToken: number }) {
  const { t } = useI18n();
  const [items, setItems] = useState<PriceRecord[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  useEffect(() => {
    let active = true;
    apiFetch<PricePage>(`/catalog/products/${productId}/prices?limit=${HISTORY_PAGE}&offset=0`).then(
      (r) => {
        if (!active) return;
        setItems(r.items);
        setTotal(r.total);
        setError(null);
      },
      (err) => active && setError(errorMessage(err, t)),
    );
    return () => {
      active = false;
    };
  }, [productId, reloadToken, t]);

  async function more() {
    if (!items) return;
    setLoadingMore(true);
    try {
      const r = await apiFetch<PricePage>(`/catalog/products/${productId}/prices?limit=${HISTORY_PAGE}&offset=${items.length}`);
      setItems([...items, ...r.items]);
      setTotal(r.total);
    } catch (err) {
      setError(errorMessage(err, t));
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <Card title={t("catalog.priceHistory")}>
      {error && <Alert>{error}</Alert>}
      {!items && !error && <LoadingBlock label={t("common.loading")} />}
      {items && items.length === 0 && <EmptyState title={t("catalog.priceHistoryEmpty")} />}
      {items && items.length > 0 && (
        <div className="flex flex-col gap-3">
          <ul className="divide-y divide-zinc-200 text-sm dark:divide-zinc-800" data-testid="price-history">
            {items
              .filter((r) => showCost || r.price_type === "selling")
              .map((r) => (
                <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span className="flex items-center gap-2">
                    <Badge tone={r.price_type === "cost" ? "warn" : "good"}>{t(`catalog.priceType.${r.price_type}`)}</Badge>
                    <strong>{formatPaise(r.price_paise)}</strong>
                  </span>
                  <span className="text-zinc-500">{formatDateTime(r.effective_from)}</span>
                </li>
              ))}
          </ul>
          {items.length < total && (
            <Button variant="secondary" onClick={() => void more()} loading={loadingMore}>
              {t("common.loadMore")}
            </Button>
          )}
        </div>
      )}
    </Card>
  );
}

const ALIAS_LANGUAGES: { value: "" | Language; label: string }[] = [
  { value: "", label: "—" },
  { value: "hinglish", label: "Hinglish" },
  { value: "hi", label: "हिन्दी" },
  { value: "en", label: "English" },
  { value: "pa", label: "ਪੰਜਾਬੀ" },
];

function AliasesCard({ product, canManage }: { product: Product; canManage: boolean }) {
  const { t } = useI18n();
  const [aliases, setAliases] = useState<ProductAlias[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [lang, setLang] = useState<"" | Language>("");
  const [fieldError, setFieldError] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);
  const key = useRef(newIdempotencyKey());

  const load = useCallback(
    () =>
      apiFetch<{ items: ProductAlias[] }>(`/catalog/products/${product.id}/aliases`).then(
        (r) => {
          setAliases(r.items);
          setError(null);
        },
        (err) => setError(errorMessage(err, t)),
      ),
    [product.id, t],
  );
  useEffect(() => {
    void load();
  }, [load]);

  async function add(event: React.FormEvent) {
    event.preventDefault();
    setFieldError(undefined);
    setError(null);
    if (!text.trim()) {
      setFieldError(t("error.required"));
      return;
    }
    setBusy(true);
    try {
      await apiFetch<ProductAlias>(`/catalog/products/${product.id}/aliases`, {
        method: "POST",
        idempotencyKey: key.current,
        body: { alias_text: text.trim(), language: lang || null },
      });
      key.current = newIdempotencyKey();
      setText("");
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.status >= 400 && err.status < 500) key.current = newIdempotencyKey();
      const fields = formErrors(err, t);
      if (fields.alias_text) setFieldError(fields.alias_text);
      else setError(errorMessage(err, t));
    } finally {
      setBusy(false);
    }
  }

  async function remove(alias: ProductAlias) {
    setError(null);
    try {
      await apiFetch<void>(`/catalog/products/${product.id}/aliases/${alias.id}`, { method: "DELETE" });
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 404)) setError(errorMessage(err, t)); // 404: already removed
    }
    await load();
  }

  return (
    <Card title={t("catalog.aliases")}>
      <div className="flex flex-col gap-3">
        <p className="text-sm text-zinc-500">{t("catalog.aliasesHelp")}</p>
        {error && <Alert>{error}</Alert>}
        {!aliases && !error && <LoadingBlock label={t("common.loading")} />}
        {aliases && aliases.length === 0 && <p className="text-sm text-zinc-500">{t("catalog.aliasesEmpty")}</p>}
        {aliases && aliases.length > 0 && (
          <ul className="flex flex-wrap gap-2" data-testid="alias-list">
            {aliases.map((a) => (
              <li key={a.id} className="flex items-center gap-1 rounded-full bg-zinc-100 py-1 pr-1 pl-3 text-sm dark:bg-zinc-800">
                <span>{a.alias_text}</span>
                {canManage && (
                  <button
                    type="button"
                    onClick={() => void remove(a)}
                    aria-label={`${t("catalog.aliasRemove")}: ${a.alias_text}`}
                    className="flex h-8 w-8 items-center justify-center rounded-full text-zinc-500 hover:bg-zinc-200 hover:text-red-700 dark:hover:bg-zinc-700"
                  >
                    ×
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
        {canManage && (
          <form onSubmit={add} noValidate className="grid gap-3 sm:grid-cols-[1fr_10rem_auto] sm:items-start">
            <TextField label={t("catalog.aliasLabel")} value={text} onChange={(e) => setText(e.target.value)} error={fieldError} maxLength={120} autoComplete="off" />
            <SelectField label={t("common.language")} value={lang} onChange={(e) => setLang(e.target.value as "" | Language)} options={ALIAS_LANGUAGES} />
            <Button type="submit" loading={busy} className="sm:mt-6">
              {t("catalog.aliasAdd")}
            </Button>
          </form>
        )}
      </div>
    </Card>
  );
}

function ArchiveProduct({ product, onArchived }: { product: Product; onArchived: (p: Product) => void }) {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <section className="flex flex-col gap-2">
      {error && <Alert>{error}</Alert>}
      <ConfirmAction
        label={t("catalog.archive")}
        question={t("catalog.archiveConfirm")}
        confirmLabel={t("catalog.archive")}
        cancelLabel={t("common.cancel")}
        busy={busy}
        onConfirm={async () => {
          setBusy(true);
          setError(null);
          try {
            onArchived(await apiFetch<Product>(`/catalog/products/${product.id}/archive`, { method: "POST" }));
          } catch (err) {
            setError(errorMessage(err, t));
          } finally {
            setBusy(false);
          }
        }}
      />
    </section>
  );
}
