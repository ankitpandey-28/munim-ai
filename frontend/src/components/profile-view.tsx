"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Card, LoadingBlock, TextField } from "@/components/ui";
import { ApiError, apiFetch } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useI18n } from "@/lib/i18n/language-provider";
import { useSession } from "@/lib/session";
import type { Me, SessionInfo } from "@/lib/types";
import { passwordIssues } from "@/lib/validation";

export function ProfileView() {
  const { t } = useI18n();
  const { me, logout } = useSession();
  const router = useRouter();
  if (!me) return <LoadingBlock label={t("common.loading")} />;
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{t("profile.title")}</h1>
        <p className="text-sm text-zinc-500">
          {me.user.name} · {me.user.phone}
        </p>
      </div>
      {me.user.must_change_password && <Alert kind="info">{t("profile.mustChange")}</Alert>}
      <ChangePasswordCard />
      {!me.user.must_change_password && <SessionsCard />}
      <Button
        variant="secondary"
        onClick={async () => {
          await logout(true);
          router.replace("/login");
        }}
      >
        {t("auth.logoutAll")}
      </Button>
    </div>
  );
}

function ChangePasswordCard() {
  const { t } = useI18n();
  const { me, setMe } = useSession();
  const router = useRouter();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const forced = me?.user.must_change_password ?? false;

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    const fieldErrors: Record<string, string> = {};
    if (!current) fieldErrors.current = t("error.required");
    const issues = passwordIssues(next, me?.user.phone);
    if (issues.includes("too_short")) fieldErrors.next = t("error.passwordShort");
    else if (issues.includes("too_long")) fieldErrors.next = t("error.passwordLong");
    else if (issues.includes("same_as_phone")) fieldErrors.next = t("error.passwordPhone");
    setErrors(fieldErrors);
    setMessage(null);
    if (Object.keys(fieldErrors).length) return;
    setSubmitting(true);
    try {
      const updated = await apiFetch<Me>("/auth/change-password", {
        method: "POST",
        body: { current_password: current, new_password: next },
      });
      setMe(updated);
      setCurrent("");
      setNext("");
      setMessage({ kind: "success", text: t("profile.passwordChanged") });
      if (forced) router.replace(updated.active_shop_id ? "/dashboard" : "/shops");
    } catch (err) {
      if (err instanceof ApiError && err.code === "WEAK_PASSWORD") setErrors({ next: err.message });
      else setMessage({ kind: "error", text: errorMessage(err, t) });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card title={t("profile.changePassword")}>
      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
        {message && <Alert kind={message.kind}>{message.text}</Alert>}
        <TextField label={t("profile.currentPassword")} type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} error={errors.current} />
        <TextField label={t("profile.newPassword")} hint={t("auth.passwordHint")} type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} error={errors.next} />
        <Button type="submit" loading={submitting}>
          {t("profile.changePassword")}
        </Button>
      </form>
    </Card>
  );
}

function SessionsCard() {
  const { t } = useI18n();
  const [sessions, setSessions] = useState<SessionInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    apiFetch<{ items: SessionInfo[] }>("/auth/sessions")
      .then((d) => setSessions(d.items))
      .catch((err) => setError(errorMessage(err, t)));
  }, [t]);

  useEffect(load, [load]);

  async function revoke(id: string) {
    try {
      await apiFetch<void>(`/auth/sessions/${id}`, { method: "DELETE" });
      load();
    } catch (err) {
      setError(errorMessage(err, t));
    }
  }

  return (
    <Card title={t("profile.sessions")}>
      {error && <Alert>{error}</Alert>}
      {!sessions && !error && <LoadingBlock label={t("common.loading")} />}
      {sessions && (
        <ul className="flex flex-col gap-2">
          {sessions.map((s) => (
            <li key={s.id} className="flex items-center justify-between gap-3 rounded-lg bg-zinc-50 p-3 text-sm dark:bg-zinc-900">
              <div className="min-w-0">
                <p className="truncate font-medium">{s.current ? t("profile.thisDevice") : s.user_agent || "—"}</p>
                <p className="text-xs text-zinc-500">{new Date(s.last_seen_at).toLocaleString("en-IN")}</p>
              </div>
              {!s.current && (
                <Button variant="ghost" className="min-h-10 text-sm" onClick={() => void revoke(s.id)}>
                  {t("profile.revoke")}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
