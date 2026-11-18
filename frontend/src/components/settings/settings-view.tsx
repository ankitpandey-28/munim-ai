"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Card, EmptyState, LoadingBlock, SelectField, TextField } from "@/components/ui";
import { ApiError, apiFetch, newIdempotencyKey } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { MessageKey } from "@/lib/i18n/dictionaries";
import { useI18n } from "@/lib/i18n/language-provider";
import { useSession } from "@/lib/session";
import type { CurrentShop, Member, MemberAdded, MemberPage, Role, Shop } from "@/lib/types";
import { isValidPincode, normalizeIndianMobile } from "@/lib/validation";

const PAGE_SIZE = 20;

export function SettingsView() {
  const { t } = useI18n();
  const [current, setCurrent] = useState<CurrentShop | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    apiFetch<CurrentShop>("/shops/current")
      .then(setCurrent)
      .catch((err) => setError(errorMessage(err, t)));
  }, [t]);
  useEffect(load, [load]);

  if (error) return <Alert>{error}</Alert>;
  if (!current) return <LoadingBlock label={t("common.loading")} />;
  const canEdit = current.role === "owner" || current.role === "admin";
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <h1 className="text-2xl font-semibold tracking-tight">{t("nav.settings")}</h1>
      <ShopDetailsCard key={current.shop.version} shop={current.shop} canEdit={canEdit} onSaved={(shop) => setCurrent({ ...current, shop })} onConflict={load} />
      {canEdit && <MembersCard role={current.role} />}
    </div>
  );
}

function ShopDetailsCard({
  shop,
  canEdit,
  onSaved,
  onConflict,
}: {
  shop: Shop;
  canEdit: boolean;
  onSaved: (shop: Shop) => void;
  onConflict: () => void;
}) {
  const { t } = useI18n();
  const { refresh } = useSession();
  const [form, setForm] = useState({
    name: shop.name,
    address: shop.address ?? "",
    city: shop.city ?? "",
    state: shop.state ?? "",
    pincode: shop.pincode ?? "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ kind: "error" | "success" | "info"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    const next: Record<string, string> = {};
    if (!form.name.trim()) next.name = t("error.required");
    if (form.pincode && !isValidPincode(form.pincode)) next.pincode = t("error.pincode");
    setErrors(next);
    setMessage(null);
    if (Object.keys(next).length) return;
    setSaving(true);
    try {
      const updated = await apiFetch<Shop>("/shops/current", {
        method: "PATCH",
        idempotencyKey: true,
        body: {
          version: shop.version,
          name: form.name.trim(),
          address: form.address.trim() || null,
          city: form.city.trim() || null,
          state: form.state.trim() || null,
          pincode: form.pincode || null,
        },
      });
      onSaved(updated);
      void refresh();
      setMessage({ kind: "success", text: "✓" });
    } catch (err) {
      if (err instanceof ApiError && err.code === "VERSION_CONFLICT") {
        setMessage({ kind: "info", text: t("shop.versionConflict") });
        onConflict();
      } else {
        setMessage({ kind: "error", text: errorMessage(err, t) });
      }
    } finally {
      setSaving(false);
    }
  }

  const field = (key: keyof typeof form, label: MessageKey, extra: Partial<React.ComponentProps<typeof TextField>> = {}) => (
    <TextField
      label={t(label)}
      value={form[key]}
      onChange={(e) => setForm({ ...form, [key]: e.target.value })}
      error={errors[key]}
      disabled={!canEdit}
      {...extra}
    />
  );

  return (
    <Card title={t("shop.details")}>
      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
        {message && <Alert kind={message.kind}>{message.text}</Alert>}
        {field("name", "shop.name", { maxLength: 120 })}
        {field("address", "shop.address", { optionalLabel: t("common.optional"), maxLength: 500 })}
        <div className="grid gap-4 sm:grid-cols-3">
          {field("city", "shop.city", { maxLength: 80 })}
          {field("state", "shop.state", { maxLength: 80 })}
          {field("pincode", "shop.pincode", { inputMode: "numeric", maxLength: 6 })}
        </div>
        {canEdit && (
          <Button type="submit" loading={saving}>
            {saving ? t("common.saving") : t("common.save")}
          </Button>
        )}
      </form>
    </Card>
  );
}

function MembersCard({ role }: { role: Role }) {
  const { t } = useI18n();
  const { me } = useSession();
  const [members, setMembers] = useState<Member[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    (offset = 0) =>
      apiFetch<MemberPage>(`/shops/current/members?limit=${PAGE_SIZE}&offset=${offset}`).then(
        (page) => {
          setMembers((prev) => (offset === 0 || !prev ? page.items : [...prev, ...page.items]));
          setTotal(page.total);
        },
        (err) => setError(errorMessage(err, t)),
      ),
    [t],
  );
  useEffect(() => {
    let active = true;
    apiFetch<MemberPage>(`/shops/current/members?limit=${PAGE_SIZE}&offset=0`).then(
      (page) => {
        if (!active) return;
        setMembers(page.items);
        setTotal(page.total);
      },
      (err) => active && setError(errorMessage(err, t)),
    );
    return () => {
      active = false;
    };
  }, [t]);

  async function act(path: string, method: "PATCH" | "POST", body?: unknown) {
    setError(null);
    try {
      await apiFetch<Member>(path, { method, body });
      await load(0);
    } catch (err) {
      setError(errorMessage(err, t));
    }
  }

  const roleOptions = (["owner", "admin", "staff"] as Role[]).map((r) => ({ value: r, label: t(`shop.role.${r}` as MessageKey) }));

  return (
    <Card title={t("members.title")}>
      <div className="flex flex-col gap-4">
        {error && <Alert>{error}</Alert>}
        {!members && !error && <LoadingBlock label={t("common.loading")} />}
        {members && members.length === 0 && <EmptyState title={t("members.empty")} />}
        {members && members.length > 0 && (
          <ul className="flex flex-col gap-2">
            {members.map((m) => {
              const isSelf = m.user_id === me?.user.id;
              const canManage = role === "owner" || m.role === "staff";
              return (
                <li key={m.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-zinc-50 p-3 dark:bg-zinc-900">
                  <div>
                    <p className="font-medium">
                      {m.name} {isSelf && <span className="text-xs text-zinc-500">({t("members.you")})</span>}
                    </p>
                    <p className="text-xs text-zinc-500">{m.phone_masked}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    {role === "owner" ? (
                      <select
                        aria-label={t("members.makeRole")}
                        value={m.role}
                        onChange={(e) => void act(`/shops/current/members/${m.id}`, "PATCH", { role: e.target.value })}
                        className="min-h-10 rounded-lg border border-zinc-300 bg-white px-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                      >
                        {roleOptions.map((o) => (
                          <option key={o.value} value={o.value}>
                            {o.label}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <span className="text-sm">{t(`shop.role.${m.role}` as MessageKey)}</span>
                    )}
                    {canManage && !isSelf && (
                      <Button variant="ghost" className="min-h-10 text-sm text-red-700" onClick={() => void act(`/shops/current/members/${m.id}/deactivate`, "POST")}>
                        {t("members.deactivate")}
                      </Button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        {members && members.length < total && (
          <Button variant="secondary" onClick={() => void load(members.length)}>
            …
          </Button>
        )}
        <AddMemberForm canAddPrivileged={role === "owner"} onAdded={() => void load(0)} />
      </div>
    </Card>
  );
}

function AddMemberForm({ canAddPrivileged, onAdded }: { canAddPrivileged: boolean; onAdded: () => void }) {
  const { t } = useI18n();
  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("staff");
  const [tempPassword, setTempPassword] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const key = useRef(newIdempotencyKey());

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    const normalized = normalizeIndianMobile(phone);
    setErrors(normalized ? {} : { phone: t("error.phone") });
    setMessage(null);
    if (!normalized) return;
    setSubmitting(true);
    try {
      const result = await apiFetch<MemberAdded>("/shops/current/members", {
        method: "POST",
        idempotencyKey: key.current,
        body: { phone: normalized, role, name: name.trim() || null, temporary_password: tempPassword || null },
      });
      setMessage({ kind: "success", text: result.account_created ? t("members.accountCreated") : t("members.added") });
      setPhone("");
      setName("");
      setTempPassword("");
      key.current = newIdempotencyKey();
      onAdded();
    } catch (err) {
      if (err instanceof ApiError) setErrors(err.fieldErrors());
      setMessage({ kind: "error", text: errorMessage(err, t) });
    } finally {
      setSubmitting(false);
    }
  }

  const roles: Role[] = canAddPrivileged ? ["staff", "admin", "owner"] : ["staff"];
  return (
    <form onSubmit={onSubmit} noValidate className="mt-2 flex flex-col gap-3 border-t border-zinc-200 pt-4 dark:border-zinc-800">
      <h3 className="font-medium">{t("members.add")}</h3>
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField label={t("auth.phone")} type="tel" inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} error={errors.phone} />
        <TextField label={t("auth.name")} value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <SelectField label={t("members.role")} value={role} onChange={(e) => setRole(e.target.value as Role)} options={roles.map((r) => ({ value: r, label: t(`shop.role.${r}` as MessageKey) }))} />
        <TextField label={t("members.tempPassword")} hint={t("members.tempPasswordHint")} type="password" autoComplete="new-password" value={tempPassword} onChange={(e) => setTempPassword(e.target.value)} error={errors.temporary_password} />
      </div>
      <Button type="submit" loading={submitting}>
        {submitting ? t("members.adding") : t("members.add")}
      </Button>
    </form>
  );
}
