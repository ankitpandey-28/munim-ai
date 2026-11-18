"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Alert, Button, TextField } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useI18n } from "@/lib/i18n/language-provider";
import { landingPath } from "@/lib/redirects";
import { useSession } from "@/lib/session";
import type { Me } from "@/lib/types";
import { normalizeIndianMobile } from "@/lib/validation";

export function LoginForm() {
  const { t } = useI18n();
  const { setMe } = useSession();
  const router = useRouter();
  const params = useSearchParams();
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    const errors: Record<string, string> = {};
    const normalized = normalizeIndianMobile(phone);
    if (!normalized) errors.phone = t("error.phone");
    if (!password) errors.password = t("error.required");
    setFieldErrors(errors);
    setFormError(null);
    if (Object.keys(errors).length) return;
    setSubmitting(true);
    try {
      const me = await apiFetch<Me>("/auth/login", {
        method: "POST",
        body: { phone: normalized, password },
      });
      setMe(me);
      router.replace(landingPath(me, params.get("next")));
    } catch (error) {
      setFormError(errorMessage(error, t));
      setPassword("");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold tracking-tight">{t("auth.login")}</h1>
      {formError && <Alert>{formError}</Alert>}
      <TextField
        label={t("auth.phone")}
        hint={t("auth.phoneHint")}
        type="tel"
        inputMode="tel"
        autoComplete="tel"
        value={phone}
        onChange={(e) => setPhone(e.target.value)}
        error={fieldErrors.phone}
        required
      />
      <TextField
        label={t("auth.password")}
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        error={fieldErrors.password}
        required
      />
      <Button type="submit" loading={submitting}>
        {submitting ? t("auth.loggingIn") : t("auth.login")}
      </Button>
      <p className="text-xs text-zinc-500">{t("auth.forgotPassword")}</p>
      <p className="text-sm">
        {t("auth.noAccount")}{" "}
        <Link href="/register" className="font-medium text-emerald-700 underline dark:text-emerald-400">
          {t("auth.register")}
        </Link>
      </p>
    </form>
  );
}
