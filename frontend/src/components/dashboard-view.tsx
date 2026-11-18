"use client";

import Link from "next/link";
import { Card, EmptyState } from "@/components/ui";
import { useI18n } from "@/lib/i18n/language-provider";
import type { MessageKey } from "@/lib/i18n/dictionaries";
import { useSession } from "@/lib/session";

const METRICS: MessageKey[] = [
  "dashboard.metric.totalSales",
  "dashboard.metric.cashCollected",
  "dashboard.metric.creditSales",
  "dashboard.metric.outstanding",
  "dashboard.metric.expenses",
];

/** Dashboard placeholder: the seven-metric business summary arrives with Phase 3/4 data. */
export function DashboardView() {
  const { t } = useI18n();
  const { me } = useSession();
  const shop = me?.memberships.find((m) => m.shop_id === me.active_shop_id);
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
      <div>
        <p className="text-sm text-zinc-500">{shop?.shop_name}</p>
        <h1 className="text-2xl font-semibold tracking-tight">
          {t("dashboard.welcome")}, {me?.user.name}
        </h1>
      </div>
      <Card title={t("dashboard.summaryTitle")}>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {METRICS.map((key) => (
            <div key={key} className="rounded-lg bg-zinc-50 p-3 dark:bg-zinc-900">
              <p className="text-xs text-zinc-500">{t(key)}</p>
              <p className="mt-1 text-xl font-semibold text-zinc-400">—</p>
            </div>
          ))}
        </div>
        <div className="mt-4">
          <EmptyState title={t("dashboard.summaryEmpty")} />
        </div>
      </Card>
      <Card title={t("dashboard.nextSteps")}>
        <ul className="list-disc space-y-2 pl-5 text-sm">
          <li>
            <Link href="/settings" className="text-emerald-700 underline dark:text-emerald-400">
              {t("dashboard.stepMembers")}
            </Link>
          </li>
          <li>{t("dashboard.stepProducts")}</li>
        </ul>
      </Card>
    </div>
  );
}
