"use client";

import { useRef, useState } from "react";
import { Alert, Badge, Button, Card, CheckboxField, ConfirmAction, EmptyState, LoadingBlock, TextField } from "@/components/ui";
import { ApiError, apiFetch, newIdempotencyKey } from "@/lib/api";
import type { Category } from "@/lib/catalog";
import { errorMessage, formErrors } from "@/lib/errors";
import { useI18n } from "@/lib/i18n/language-provider";
import { CatalogHeader, useCatalogPermissions, useCategories } from "./shared";

interface CategoryFormState {
  name: string;
  name_hi: string;
  sort_order: string;
}

function parseSortOrder(value: string): number | null {
  const v = value.trim();
  if (!v) return 0;
  if (!/^-?\d{1,9}$/.test(v)) return null;
  return Number(v);
}

export function CategoriesView() {
  const { t } = useI18n();
  const perms = useCatalogPermissions();
  const [includeArchived, setIncludeArchived] = useState(false);
  const { categories, error, reload } = useCategories(includeArchived);

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-5">
      <CatalogHeader />
      {!perms.manage && <Alert kind="info">{t("catalog.viewOnly")}</Alert>}
      {perms.manage && (
        <Card title={t("category.add")}>
          <CategoryForm category={null} onSaved={reload} />
        </Card>
      )}
      <CheckboxField label={t("catalog.includeArchived")} checked={includeArchived} onChange={(e) => setIncludeArchived(e.target.checked)} />
      {error && <Alert>{error}</Alert>}
      {!categories && !error && <LoadingBlock label={t("common.loading")} />}
      {categories && categories.length === 0 && <EmptyState title={t("category.empty")} />}
      {categories && categories.length > 0 && (
        <ul className="flex flex-col gap-2" data-testid="category-list">
          {categories.map((c) => (
            <CategoryRow key={`${c.id}-${c.updated_at}`} category={c} canManage={perms.manage} onChanged={reload} />
          ))}
        </ul>
      )}
    </div>
  );
}

function CategoryRow({ category, canManage, onChanged }: { category: Category; canManage: boolean; onChanged: () => void }) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const archived = Boolean(category.archived_at);

  if (editing) {
    return (
      <li className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
        <CategoryForm category={category} onSaved={onChanged} onCancel={() => setEditing(false)} />
      </li>
    );
  }
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="flex items-center gap-2 font-medium">
            {category.name}
            {archived && <Badge tone="warn">{t("catalog.archived")}</Badge>}
          </p>
          <p className="text-xs text-zinc-500">
            {category.name_hi ? `${category.name_hi} · ` : ""}
            {t("category.sortOrder")}: {category.sort_order}
          </p>
        </div>
        {canManage && !archived && (
          <div className="flex flex-wrap items-start gap-2">
            <Button variant="secondary" className="min-h-10" onClick={() => setEditing(true)}>
              {t("common.edit")}
            </Button>
            <ConfirmAction
              label={t("category.archive")}
              question={t("category.archiveConfirm")}
              confirmLabel={t("category.archive")}
              cancelLabel={t("common.cancel")}
              busy={busy}
              onConfirm={async () => {
                setBusy(true);
                setError(null);
                try {
                  await apiFetch<Category>(`/catalog/categories/${category.id}/archive`, { method: "POST" });
                  onChanged();
                } catch (err) {
                  setError(errorMessage(err, t));
                } finally {
                  setBusy(false);
                }
              }}
            />
          </div>
        )}
      </div>
      {error && <Alert>{error}</Alert>}
    </li>
  );
}

function CategoryForm({ category, onSaved, onCancel }: { category: Category | null; onSaved: () => void; onCancel?: () => void }) {
  const { t } = useI18n();
  const [form, setForm] = useState<CategoryFormState>({
    name: category?.name ?? "",
    name_hi: category?.name_hi ?? "",
    sort_order: String(category?.sort_order ?? 0),
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ kind: "error" | "success" | "info"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const key = useRef(newIdempotencyKey());

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setMessage(null);
    const next: Record<string, string> = {};
    if (!form.name.trim()) next.name = t("error.required");
    const sortOrder = parseSortOrder(form.sort_order);
    if (sortOrder === null) next.sort_order = t("error.quantityWhole");
    setErrors(next);
    if (Object.keys(next).length) return;

    const body: Record<string, unknown> = { name: form.name.trim(), name_hi: form.name_hi.trim() || null, sort_order: sortOrder };
    if (category) {
      const original: Record<string, unknown> = { name: category.name, name_hi: category.name_hi, sort_order: category.sort_order };
      for (const k of Object.keys(body)) if (body[k] === original[k]) delete body[k];
      if (Object.keys(body).length === 0) {
        setMessage({ kind: "info", text: t("catalog.noChanges") });
        return;
      }
    }
    setSaving(true);
    try {
      await apiFetch<Category>(category ? `/catalog/categories/${category.id}` : "/catalog/categories", {
        method: category ? "PATCH" : "POST",
        idempotencyKey: key.current,
        body,
      });
      key.current = newIdempotencyKey();
      if (!category) {
        setForm({ name: "", name_hi: "", sort_order: "0" });
        setMessage({ kind: "success", text: t("category.created") });
      }
      onSaved();
    } catch (err) {
      if (err instanceof ApiError && err.status >= 400 && err.status < 500) key.current = newIdempotencyKey();
      setErrors(formErrors(err, t));
      setMessage({ kind: "error", text: errorMessage(err, t) });
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
      <div className="grid gap-4 sm:grid-cols-[1fr_1fr_9rem]">
        <TextField label={t("category.name")} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} error={errors.name} maxLength={80} autoComplete="off" />
        <TextField label={t("category.nameHi")} optionalLabel={t("common.optional")} value={form.name_hi} onChange={(e) => setForm({ ...form, name_hi: e.target.value })} error={errors.name_hi} maxLength={80} lang="hi" autoComplete="off" />
        <TextField label={t("category.sortOrder")} hint={t("category.sortOrderHint")} inputMode="numeric" value={form.sort_order} onChange={(e) => setForm({ ...form, sort_order: e.target.value })} error={errors.sort_order} autoComplete="off" />
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" loading={saving}>
          {category ? t("common.save") : t("category.add")}
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
