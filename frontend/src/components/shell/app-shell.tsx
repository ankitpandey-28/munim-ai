"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { LanguageSelect } from "@/components/language-select";
import { Alert, Button, LoadingBlock } from "@/components/ui";
import { errorMessage } from "@/lib/errors";
import { useI18n } from "@/lib/i18n/language-provider";
import type { MessageKey } from "@/lib/i18n/dictionaries";
import { appNavigation } from "@/lib/navigation";
import { useSession } from "@/lib/session";

/** Routes usable without an active shop (choose/create a shop, change password). */
const SHOPLESS_ROUTES = ["/shops", "/profile"];

export function AppShell({ children }: { children: React.ReactNode }) {
  const { status, me, error, refresh } = useSession();
  const { t } = useI18n();
  const router = useRouter();
  const pathname = usePathname();

  const needsPasswordChange = me?.user.must_change_password ?? false;
  const shopless = SHOPLESS_ROUTES.some((r) => pathname.startsWith(r));

  useEffect(() => {
    if (status === "unauthenticated") {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    } else if (status === "authenticated" && me) {
      if (needsPasswordChange && !pathname.startsWith("/profile")) router.replace("/profile?force=1");
      else if (!needsPasswordChange && !me.active_shop_id && !shopless) router.replace("/shops");
    }
  }, [status, me, needsPasswordChange, shopless, pathname, router]);

  if (status === "loading" || status === "unauthenticated") {
    return <LoadingBlock label={t("common.loading")} />;
  }
  if (status === "error") {
    return (
      <div className="mx-auto mt-16 flex max-w-md flex-col gap-4 px-4">
        <Alert>{errorMessage(error, t)}</Alert>
        <Button variant="secondary" onClick={() => void refresh()}>
          {t("common.retry")}
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col">
      <TopBar />
      <div className="flex flex-1 flex-col md:flex-row">
        {!needsPasswordChange && me?.active_shop_id && <SideNav pathname={pathname} />}
        <main className="flex-1 px-4 py-6 md:px-8">{children}</main>
      </div>
    </div>
  );
}

function TopBar() {
  const { me, logout } = useSession();
  const { t } = useI18n();
  const router = useRouter();
  const [loggingOut, setLoggingOut] = useState(false);
  const activeShop = me?.memberships.find((m) => m.shop_id === me.active_shop_id);

  async function onLogout() {
    setLoggingOut(true);
    await logout();
    router.replace("/login");
  }

  return (
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
      <div className="flex items-center gap-3">
        <Link href="/dashboard" className="text-lg font-semibold tracking-tight">
          Munim AI
        </Link>
        {me && me.memberships.length > 0 && <ShopSwitcher />}
        {activeShop && (
          <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">
            {t(`shop.role.${activeShop.role}` as MessageKey)}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2">
        <LanguageSelect compact />
        <Link
          href="/profile"
          className="min-h-10 rounded-lg px-3 py-2 text-sm font-medium hover:bg-zinc-100 dark:hover:bg-zinc-800"
        >
          {me?.user.name ?? t("nav.profile")}
        </Link>
        <Button variant="ghost" onClick={onLogout} loading={loggingOut} className="min-h-10 px-3 text-sm">
          {t("auth.logout")}
        </Button>
      </div>
    </header>
  );
}

function ShopSwitcher() {
  const { me, switchShop } = useSession();
  const { t } = useI18n();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!me) return null;

  async function onChange(event: React.ChangeEvent<HTMLSelectElement>) {
    const value = event.target.value;
    if (value === "__new") {
      router.push("/shops?new=1");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await switchShop(value);
      router.refresh();
    } catch (err) {
      setError(errorMessage(err, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <label className="flex items-center gap-2">
      <span className="sr-only">{t("shop.switch")}</span>
      <select
        value={me.active_shop_id ?? ""}
        onChange={onChange}
        disabled={busy}
        aria-label={t("shop.switch")}
        className="min-h-10 max-w-[12rem] truncate rounded-lg border border-zinc-300 bg-white px-2 text-sm font-medium dark:border-zinc-700 dark:bg-zinc-900"
      >
        {!me.active_shop_id && <option value="">{t("shop.chooseTitle")}</option>}
        {me.memberships.map((m) => (
          <option key={m.shop_id} value={m.shop_id}>
            {m.shop_name}
          </option>
        ))}
        <option value="__new">+ {t("shop.create")}</option>
      </select>
      {error && <span role="alert" className="text-xs text-red-700">{error}</span>}
    </label>
  );
}

function SideNav({ pathname }: { pathname: string }) {
  const { t } = useI18n();
  return (
    <nav
      aria-label="Main"
      className="border-b border-zinc-200 md:w-56 md:shrink-0 md:border-b-0 md:border-r dark:border-zinc-800"
    >
      <ul className="flex gap-1 overflow-x-auto px-2 py-3 md:flex-col md:overflow-visible">
        {appNavigation.map((item) => {
          const active = pathname.startsWith(item.href);
          return (
            <li key={item.href} className="shrink-0">
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`flex min-h-12 items-center rounded-lg px-3 py-2 text-sm font-medium ${
                  active
                    ? "bg-emerald-50 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100"
                    : "hover:bg-zinc-100 dark:hover:bg-zinc-900"
                }`}
              >
                {t(item.labelKey)}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
