"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Alert, Button, Card, EmptyState, LoadingBlock, TextField } from "@/components/ui";
import { apiFetch, newIdempotencyKey } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { MessageKey } from "@/lib/i18n/dictionaries";
import { useI18n } from "@/lib/i18n/language-provider";
import { useSession } from "@/lib/session";
import type { CurrentShop, MyShop } from "@/lib/types";
import { isValidPincode } from "@/lib/validation";

export function ShopsView() {
  const { t } = useI18n();
  const { switchShop, refresh } = useSession();
  const router = useRouter();
  const params = useSearchParams();
  const [shops, setShops] = useState<MyShop[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(params.get("new") === "1");

  useEffect(() => {
    apiFetch<{ items: MyShop[] }>("/shops/mine")
      .then((data) => {
        setShops(data.items);
        if (data.items.length === 0) setShowCreate(true);
      })
      .catch((err) => setError(errorMessage(err, t)));
  }, [t]);

  async function open(shopId: string) {
    setBusyId(shopId);
    setError(null);
    try {
      await switchShop(shopId);
      router.push("/dashboard");
    } catch (err) {
      setError(errorMessage(err, t));
      setBusyId(null);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6">
      <h1 className="text-2xl font-semibold tracking-tight">{t("nav.shops")}</h1>
      {error && <Alert>{error}</Alert>}
      {shops === null && !error && <LoadingBlock label={t("common.loading")} />}
      {shops && shops.length === 0 && !showCreate && <EmptyState title={t("shop.none")} />}
      {shops && shops.length > 0 && (
        <ul className="flex flex-col gap-2">
          {shops.map((s) => (
            <li
              key={s.shop_id}
              className="flex items-center justify-between gap-3 rounded-xl border border-zinc-200 p-4 dark:border-zinc-800"
            >
              <div>
                <p className="font-medium">{s.name}</p>
                <p className="text-sm text-zinc-500">
                  {t(`shop.role.${s.role}` as MessageKey)}
                  {s.is_active && ` · ${t("shop.active")}`}
                </p>
              </div>
              <Button variant="secondary" loading={busyId === s.shop_id} onClick={() => void open(s.shop_id)}>
                {t("shop.open")}
              </Button>
            </li>
          ))}
        </ul>
      )}
      {showCreate ? (
        <CreateShopForm
          onCreated={async () => {
            await refresh();
            router.push("/dashboard");
          }}
        />
      ) : (
        shops && (
          <Button variant="secondary" onClick={() => setShowCreate(true)}>
            + {t("shop.create")}
          </Button>
        )
      )}
    </div>
  );
}

function CreateShopForm({ onCreated }: { onCreated: () => Promise<void> }) {
  const { t } = useI18n();
  const [name, setName] = useState("");
  const [city, setCity] = useState("");
  const [state, setState] = useState("");
  const [pincode, setPincode] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // One key per form instance: a retried submit (e.g. after a network drop) is deduplicated.
  const idempotencyKey = useRef(newIdempotencyKey());

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    const next: Record<string, string> = {};
    if (!name.trim()) next.name = t("error.required");
    if (pincode && !isValidPincode(pincode)) next.pincode = t("error.pincode");
    setErrors(next);
    setFormError(null);
    if (Object.keys(next).length) return;
    setSubmitting(true);
    try {
      await apiFetch<CurrentShop>("/shops", {
        method: "POST",
        idempotencyKey: idempotencyKey.current,
        body: {
          name: name.trim(),
          city: city.trim() || null,
          state: state.trim() || null,
          pincode: pincode || null,
        },
      });
      await onCreated();
    } catch (err) {
      setFormError(errorMessage(err, t));
      setSubmitting(false);
    }
  }

  return (
    <Card title={t("shop.createTitle")}>
      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
        <p className="text-sm text-zinc-500">{t("shop.createHelp")}</p>
        {formError && <Alert>{formError}</Alert>}
        <TextField label={t("shop.name")} value={name} onChange={(e) => setName(e.target.value)} error={errors.name} maxLength={120} required />
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField label={t("shop.city")} optionalLabel={t("common.optional")} value={city} onChange={(e) => setCity(e.target.value)} maxLength={80} />
          <TextField label={t("shop.state")} optionalLabel={t("common.optional")} value={state} onChange={(e) => setState(e.target.value)} maxLength={80} />
        </div>
        <TextField label={t("shop.pincode")} optionalLabel={t("common.optional")} inputMode="numeric" value={pincode} onChange={(e) => setPincode(e.target.value.trim())} error={errors.pincode} maxLength={6} />
        <Button type="submit" loading={submitting}>
          {submitting ? t("common.saving") : t("shop.create")}
        </Button>
      </form>
    </Card>
  );
}
