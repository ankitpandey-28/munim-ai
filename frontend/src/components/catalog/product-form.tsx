"use client";

import { useRef, useState } from "react";
import { Alert, Button, CheckboxField, SelectField, TextField } from "@/components/ui";
import { ApiError, apiFetch, newIdempotencyKey } from "@/lib/api";
import {
  type Category,
  type Product,
  type Unit,
  changedFields,
  displayName,
  isValidBarcode,
  parseQuantity,
  parseRupeesToPaise,
} from "@/lib/catalog";
import { errorMessage, formErrors } from "@/lib/errors";
import type { MessageKey } from "@/lib/i18n/dictionaries";
import { useI18n } from "@/lib/i18n/language-provider";
import { unitLabel } from "./shared";

interface FormState {
  name: string;
  name_hi: string;
  category_id: string;
  base_unit_code: string;
  is_loose: boolean;
  selling_price: string;
  cost_price: string;
  reorder_level: string;
  barcode: string;
}

function initialState(product: Product | null, units: Unit[]): FormState {
  if (product) {
    return {
      name: product.name,
      name_hi: product.name_hi ?? "",
      category_id: product.category_id ?? "",
      base_unit_code: product.base_unit_code,
      is_loose: product.is_loose,
      selling_price: "",
      cost_price: "",
      reorder_level: product.reorder_level ? product.reorder_level.replace(/\.?0+$/, "") : "",
      barcode: product.barcode ?? "",
    };
  }
  const defaultUnit = units.find((u) => u.code === "piece")?.code ?? units[0]?.code ?? "";
  return { name: "", name_hi: "", category_id: "", base_unit_code: defaultUnit, is_loose: false, selling_price: "", cost_price: "", reorder_level: "", barcode: "" };
}

/**
 * Create (product = null) or edit a product. Editing never sends prices: prices change only through
 * the dedicated price form (the backend rejects price fields on PATCH).
 */
export function ProductForm({
  product,
  units,
  categories,
  showCost,
  onSaved,
  onConflict,
  onCancel,
}: {
  product: Product | null;
  units: Unit[];
  categories: Category[];
  showCost: boolean;
  onSaved: (product: Product, created: boolean) => void;
  onConflict?: () => void;
  onCancel?: () => void;
}) {
  const { t, language } = useI18n();
  const [form, setForm] = useState<FormState>(() => initialState(product, units));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ kind: "error" | "success" | "info"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  // One key per logical submission: a retry after a network error reuses it (no duplicate product).
  const key = useRef(newIdempotencyKey());

  const unit = units.find((u) => u.code === form.base_unit_code);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setForm((f) => ({ ...f, [k]: v }));

  function validate(): Record<string, unknown> | null {
    const next: Record<string, string> = {};
    if (!form.name.trim()) next.name = t("error.required");
    if (!unit) next.base_unit_code = t("error.required");
    if (form.is_loose && unit && !unit.allows_decimal) next.is_loose = t("error.looseUnit");
    const reorder = parseQuantity(form.reorder_level, { allowsDecimal: unit?.allows_decimal ?? false });
    if (!reorder.ok) next.reorder_level = t(reorder.error === "decimal_not_allowed" ? "error.quantityWhole" : "error.quantity");
    if (!isValidBarcode(form.barcode.trim())) next.barcode = t("error.barcode");
    const body: Record<string, unknown> = {
      name: form.name.trim(),
      name_hi: form.name_hi.trim() || null,
      category_id: form.category_id || null,
      base_unit_code: form.base_unit_code,
      is_loose: form.is_loose,
      reorder_level: reorder.ok ? reorder.value : null,
      barcode: form.barcode.trim() || null,
    };
    if (!product) {
      const selling = parseRupeesToPaise(form.selling_price);
      if (!selling.ok) next.selling_price_paise = t(amountError(selling.error));
      else body.selling_price_paise = selling.value;
      if (showCost) {
        const cost = parseRupeesToPaise(form.cost_price, { required: false });
        if (!cost.ok) next.default_cost_price_paise = t(amountError(cost.error));
        else if (cost.value !== null) body.default_cost_price_paise = cost.value;
      }
    }
    setErrors(next);
    return Object.keys(next).length ? null : body;
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setMessage(null);
    const body = validate();
    if (!body) return;
    let payload = body;
    if (product) {
      const reorder = product.reorder_level ? parseQuantity(product.reorder_level, { allowsDecimal: true }) : null;
      const original: Record<string, unknown> = {
        name: product.name,
        name_hi: product.name_hi,
        category_id: product.category_id,
        base_unit_code: product.base_unit_code,
        is_loose: product.is_loose,
        reorder_level: reorder?.ok ? reorder.value : null,
        barcode: product.barcode,
      };
      const changes = changedFields(original, body);
      if (Object.keys(changes).length === 0) {
        setMessage({ kind: "info", text: t("catalog.noChanges") });
        return;
      }
      payload = { version: product.version, ...changes };
    }
    setSaving(true);
    try {
      const saved = await apiFetch<Product>(product ? `/catalog/products/${product.id}` : "/catalog/products", {
        method: product ? "PATCH" : "POST",
        idempotencyKey: key.current,
        body: payload,
      });
      key.current = newIdempotencyKey();
      if (!product) setForm(initialState(null, units));
      setMessage({ kind: "success", text: t(product ? "catalog.saved" : "catalog.created") });
      onSaved(saved, !product);
    } catch (err) {
      // A 4xx leaves nothing behind, so the corrected attempt gets a new key. A network/5xx error
      // keeps the key: if the first request did commit, the retry replays it instead of duplicating.
      if (err instanceof ApiError && err.status >= 400 && err.status < 500) key.current = newIdempotencyKey();
      setErrors(formErrors(err, t));
      if (err instanceof ApiError && err.code === "VERSION_CONFLICT") {
        setMessage({ kind: "info", text: t("catalog.versionConflict") });
        onConflict?.();
      } else {
        setMessage({ kind: "error", text: errorMessage(err, t) });
      }
    } finally {
      setSaving(false);
    }
  }

  const unitOptions = units.map((u) => ({ value: u.code, label: unitLabel(u, u.code, language) }));
  const categoryOptions = [
    { value: "", label: t("catalog.noCategory") },
    ...categories.filter((c) => !c.archived_at || c.id === form.category_id).map((c) => ({ value: c.id, label: displayName(c, language) })),
  ];

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField label={t("catalog.field.name")} value={form.name} onChange={(e) => set("name", e.target.value)} error={errors.name} maxLength={120} autoComplete="off" required />
        <TextField
          label={t("catalog.field.nameHi")}
          optionalLabel={t("common.optional")}
          value={form.name_hi}
          onChange={(e) => set("name_hi", e.target.value)}
          error={errors.name_hi}
          maxLength={120}
          lang="hi"
          autoComplete="off"
        />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <SelectField label={t("catalog.field.category")} value={form.category_id} onChange={(e) => set("category_id", e.target.value)} options={categoryOptions} error={errors.category_id} />
        <SelectField label={t("catalog.field.unit")} value={form.base_unit_code} onChange={(e) => set("base_unit_code", e.target.value)} options={unitOptions} error={errors.base_unit_code} />
      </div>
      <CheckboxField
        label={t("catalog.field.isLoose")}
        hint={t("catalog.field.isLooseHint")}
        checked={form.is_loose}
        onChange={(e) => set("is_loose", e.target.checked)}
        error={errors.is_loose}
      />
      {!product && (
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label={t("catalog.field.sellingPrice")}
            hint={t("catalog.field.priceHint")}
            inputMode="decimal"
            value={form.selling_price}
            onChange={(e) => set("selling_price", e.target.value)}
            error={errors.selling_price_paise}
            autoComplete="off"
            required
          />
          {showCost && (
            <TextField
              label={t("catalog.field.costPrice")}
              optionalLabel={t("common.optional")}
              hint={t("catalog.field.costPriceHint")}
              inputMode="decimal"
              value={form.cost_price}
              onChange={(e) => set("cost_price", e.target.value)}
              error={errors.default_cost_price_paise}
              autoComplete="off"
            />
          )}
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField
          label={`${t("catalog.field.reorderLevel")}${unit ? ` (${unit.code})` : ""}`}
          optionalLabel={t("common.optional")}
          hint={t("catalog.field.reorderHint")}
          inputMode={unit?.allows_decimal ? "decimal" : "numeric"}
          value={form.reorder_level}
          onChange={(e) => set("reorder_level", e.target.value)}
          error={errors.reorder_level}
          autoComplete="off"
        />
        <TextField
          label={t("catalog.field.barcode")}
          optionalLabel={t("common.optional")}
          value={form.barcode}
          onChange={(e) => set("barcode", e.target.value)}
          error={errors.barcode}
          maxLength={64}
          autoComplete="off"
        />
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" loading={saving}>
          {saving ? t(product ? "common.saving" : "catalog.adding") : t(product ? "common.save" : "catalog.addProduct")}
        </Button>
        {onCancel && (
          <Button type="button" variant="secondary" onClick={onCancel} disabled={saving}>
            {t("common.cancel")}
          </Button>
        )}
      </div>
    </form>
  );
}

export function amountError(error: "required" | "invalid" | "too_large"): MessageKey {
  return error === "required" ? "error.required" : error === "too_large" ? "error.amountLarge" : "error.amount";
}
