import type { MessageKey } from "./i18n/dictionaries";

/** Navigation for the authenticated shell. Labels are i18n keys (no "kamai" anywhere). */
export type AppRoute = {
  href: string;
  labelKey: MessageKey;
  description: string;
  /** Development phase in which the screen gets real functionality (see README roadmap). */
  phase: number;
};

export const appRoutes = {
  dashboard: {
    href: "/dashboard",
    labelKey: "nav.dashboard",
    description: "Business summary: total sales, cash collected, credit sales, outstanding credit, expenses and profit.",
    phase: 4,
  },
  assistant: {
    href: "/assistant",
    labelKey: "nav.assistant",
    description: "Push-to-talk assistant in Hindi, Hinglish and Punjabi with confirmation before every write.",
    phase: 5,
  },
  sales: {
    href: "/sales",
    labelKey: "nav.sales",
    description: "Itemized and unitemized sales with cash, UPI and udhaar portions.",
    phase: 3,
  },
  catalog: {
    href: "/catalog",
    labelKey: "nav.catalog",
    description: "Products, categories, prices and other names used for search and voice.",
    phase: 3,
  },
  inventory: {
    href: "/inventory",
    labelKey: "nav.inventory",
    description: "Stock levels, stock movements and stock counts.",
    phase: 3,
  },
  customers: {
    href: "/customers",
    labelKey: "nav.customers",
    description: "Customer profiles, nicknames and reminder consent.",
    phase: 3,
  },
  udhaar: {
    href: "/udhaar",
    labelKey: "nav.udhaar",
    description: "Credit ledger, payments, allocations and ageing.",
    phase: 3,
  },
  expenses: {
    href: "/expenses",
    labelKey: "nav.expenses",
    description: "Business expenses and personal withdrawals.",
    phase: 4,
  },
  reports: {
    href: "/reports",
    labelKey: "nav.reports",
    description: "Period summaries, profit (with cost coverage) and udhaar ageing.",
    phase: 4,
  },
  suppliers: {
    href: "/suppliers",
    labelKey: "nav.suppliers",
    description: "Suppliers, purchase orders and goods receipts.",
    phase: 4,
  },
  settings: {
    href: "/settings",
    labelKey: "nav.settings",
    description: "Shop details and members.",
    phase: 2,
  },
} satisfies Record<string, AppRoute>;

export const appNavigation: AppRoute[] = Object.values(appRoutes);
