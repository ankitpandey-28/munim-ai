"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Alert, Button, TextField } from "@/components/ui";
import { ApiError, apiFetch } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useI18n } from "@/lib/i18n/language-provider";
import { landingPath } from "@/lib/redirects";
import { useSession } from "@/lib/session";
import type { Me } from "@/lib/types";
import { normalizeIndianMobile, passwordIssues } from "@/lib/validation";

export function RegisterForm() {
  const { t, language } = useI18n();
  const { setMe } = useSession();
  const router = useRouter();
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    const errors: Record<string, string> = {};
    const normalized = normalizeIndianMobile(phone);
    if (!name.trim()) errors.name = t("error.required");
    if (!normalized) errors.phone = t("error.phone");
    const issues = passwordIssues(password, normalized ?? undefined);
    if (issues.includes("too_short")) errors.password = t("error.passwordShort");
    else if (issues.includes("too_long")) errors.password = t("error.passwordLong");
    else if (issues.includes("same_as_phone")) errors.password = t("error.passwordPhone");
    setFieldErrors(errors);
    setFormError(null);
    if (Object.keys(errors).length) return;
    setSubmitting(true);
    try {
      const me = await apiFetch<Me>("/auth/register", {
        method: "POST",
        body: {
          name: name.trim(),
          phone: normalized,
          password,
          preferred_language: language,
        },
      });
      setMe(me);
      router.replace(landingPath(me));
    } catch (error) {
      if (error instanceof ApiError && error.code === "WEAK_PASSWORD") {
        setFieldErrors({ password: error.message });
      } else {
        setFormError(errorMessage(error, t));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold tracking-tight">{t("auth.register")}</h1>
      {formError && <Alert>{formError}</Alert>}
      <TextField
        label={t("auth.name")}
        autoComplete="name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        error={fieldErrors.name}
        maxLength={120}
        required
      />
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
        hint={t("auth.passwordHint")}
        type="password"
        autoComplete="new-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        error={fieldErrors.password}
        required
      />
      <Button type="submit" loading={submitting}>
        {submitting ? t("auth.creating") : t("auth.register")}
      </Button>
      <p className="text-sm">
        {t("auth.haveAccount")}{" "}
        <Link href="/login" className="font-medium text-emerald-700 underline dark:text-emerald-400">
          {t("auth.login")}
        </Link>
      </p>
    </form>
  );
}
