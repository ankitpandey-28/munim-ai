/**
 * Catalogue types (mirroring backend/app/modules/catalog/schemas.py) and pure helpers for money,
 * quantities, permissions and list queries. Money is always integer paise: user input in rupees is
 * converted with string arithmetic only (no floating point), and the backend computes everything
 * authoritative.
 */

import type { Language, Role } from "./types";

export const MAX_PAISE = 2 ** 53 - 1;
export const PRODUCT_PAGE_SIZE = 50;

export interface Unit {
  code: string;
  dimension: "mass" | "volume" | "count";
  factor_to_dimension_base: string;
  allows_decimal: boolean;
  name_en: string;
  name_hi: string;
  spoken_forms: string[];
}

export interface Category {
  id: string;
  name: string;
  name_hi: string | null;
  sort_order: number;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Product {
  id: string;
  name: string;
  name_hi: string | null;
  category_id: string | null;
  base_unit_code: string;
  is_loose: boolean;
  track_stock: boolean;
  selling_price_paise: number;
  /** Always null for roles without `catalog.view_costs` (the backend never sends it). */
  default_cost_price_paise: number | null;
  costs_visible: boolean;
  reorder_level: string | null;
  barcode: string | null;
  archived_at: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface ProductAlias {
  id: string;
  product_id: string;
  alias_text: string;
  language: Language | null;
  source: "seed" | "manual" | "learned";
  created_at: string;
}

export interface PriceRecord {
  id: string;
  product_id: string;
  price_type: "selling" | "cost";
  price_paise: number;
  effective_from: string;
  set_by_user_id: string | null;
  source: "manual" | "voice" | "system";
  created_at: string;
}

export interface ProductPage {
  items: Product[];
  total: number;
  limit: number;
  offset: number;
}

export interface PricePage {
  items: PriceRecord[];
  total: number;
  limit: number;
  offset: number;
  costs_visible: boolean;
}

// ----------------------------------------------------------------------------- permissions

/** Mirrors backend ROLE_PERMISSIONS (app/modules/shops/permissions.py). UI hints only: the
 *  backend enforces every rule and never sends cost data to roles without `view_costs`. */
export interface CatalogPermissions {
  view: boolean;
  viewCosts: boolean;
  manage: boolean;
  managePrices: boolean;
}

export function catalogPermissions(role: Role | null | undefined): CatalogPermissions {
  const full = role === "owner" || role === "admin";
  return { view: role != null, viewCosts: full, manage: full, managePrices: full };
}

// ----------------------------------------------------------------------------- money

/** "₹1,23,456.50" from paise, using integer arithmetic and Indian digit grouping. */
export function formatPaise(paise: number | null | undefined): string {
  if (paise == null || !Number.isSafeInteger(paise)) return "—";
  const negative = paise < 0;
  const abs = Math.abs(paise);
  const rupees = Math.floor(abs / 100);
  const fraction = abs % 100;
  const grouped = groupIndian(String(rupees));
  return `${negative ? "−" : ""}₹${grouped}${fraction ? "." + String(fraction).padStart(2, "0") : ""}`;
}

/** Rupees for an input box ("44.50" / "44"), from paise. */
export function paiseToRupeeInput(paise: number | null | undefined): string {
  if (paise == null) return "";
  const rupees = Math.floor(paise / 100);
  const fraction = paise % 100;
  return fraction ? `${rupees}.${String(fraction).padStart(2, "0")}` : String(rupees);
}

function groupIndian(digits: string): string {
  if (digits.length <= 3) return digits;
  const last3 = digits.slice(-3);
  const rest = digits.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",");
  return `${rest},${last3}`;
}

export type ParseResult<T> = { ok: true; value: T } | { ok: false; error: "required" | "invalid" | "too_large" };

/** Parse a rupee amount typed by a person ("44", "44.5", "1,200.00", "₹ 30") into paise. */
export function parseRupeesToPaise(input: string, { required = true } = {}): ParseResult<number | null> {
  const cleaned = input.replace(/[₹,\s]/g, "");
  if (!cleaned) return required ? { ok: false, error: "required" } : { ok: true, value: null };
  const match = /^(\d{1,14})(?:\.(\d{1,2}))?$/.exec(cleaned);
  if (!match) return { ok: false, error: "invalid" };
  const whole = Number(match[1]);
  const fraction = Number((match[2] ?? "").padEnd(2, "0"));
  const paise = whole * 100 + fraction;
  if (!Number.isSafeInteger(paise) || paise > MAX_PAISE) return { ok: false, error: "too_large" };
  return { ok: true, value: paise };
}

// ----------------------------------------------------------------------------- quantities

/** Validate a quantity (e.g. reorder level) as a decimal string with at most 3 places. Count
 *  units (allows_decimal = false) accept whole numbers only. Returns the string to send. */
export function parseQuantity(
  input: string,
  { allowsDecimal, required = false }: { allowsDecimal: boolean; required?: boolean },
): ParseResult<string | null> | { ok: false; error: "decimal_not_allowed" } {
  const cleaned = input.trim();
  if (!cleaned) return required ? { ok: false, error: "required" } : { ok: true, value: null };
  const match = /^(\d{1,11})(?:\.(\d{1,3}))?$/.exec(cleaned);
  if (!match) return { ok: false, error: "invalid" };
  const fraction = (match[2] ?? "").replace(/0+$/, "");
  if (fraction && !allowsDecimal) return { ok: false, error: "decimal_not_allowed" };
  return { ok: true, value: fraction ? `${match[1]}.${fraction}` : match[1] };
}

/** "30.000" → "30", "2.500" → "2.5" for display. */
export function formatQuantity(value: string | null | undefined): string {
  if (value == null) return "—";
  return value.includes(".") ? value.replace(/\.?0+$/, "") : value;
}

// ----------------------------------------------------------------------------- queries

export interface ProductFilters {
  q?: string;
  categoryId?: string;
  includeArchived?: boolean;
  offset?: number;
  limit?: number;
}

/** Query string for GET /catalog/products. Never includes a shop id (the backend rejects it). */
export function productQuery(filters: ProductFilters): string {
  const params = new URLSearchParams();
  const q = filters.q?.trim();
  if (q) params.set("q", q.slice(0, 120));
  if (filters.categoryId) params.set("category_id", filters.categoryId);
  if (filters.includeArchived) params.set("include_archived", "true");
  params.set("limit", String(filters.limit ?? PRODUCT_PAGE_SIZE));
  params.set("offset", String(filters.offset ?? 0));
  return params.toString();
}

/** Barcode rule mirrored from the backend: optional, ≤ 64 chars, no whitespace/control chars. */
export function isValidBarcode(value: string): boolean {
  if (!value) return true;
  return value.length <= 64 && !/[\s\p{C}]/u.test(value);
}

/** Display name in the chosen UI language: Hindi name when the UI is Hindi and one exists. */
export function displayName(item: { name: string; name_hi: string | null }, uiLanguage: string): string {
  return uiLanguage === "hi" && item.name_hi ? item.name_hi : item.name;
}

/** Fields that changed between the original product and the edit form (PATCH body, sans version). */
export function changedFields<T extends Record<string, unknown>>(original: T, next: T): Partial<T> {
  const out: Partial<T> = {};
  for (const key of Object.keys(next) as (keyof T)[]) {
    if (next[key] !== original[key]) out[key] = next[key];
  }
  return out;
}

/** "Cheeni, chini , Shakkar" -> ["Cheeni", "Shakkar"]: trimmed, blanks dropped, case-insensitive dedupe. */
export function parseAliases(input: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of input.split(/[,\n]/)) {
    const alias = raw.trim().replace(/\s+/g, " ");
    const key = alias.toLocaleLowerCase();
    if (alias && !seen.has(key)) {
      seen.add(key);
      out.push(alias);
    }
  }
  return out;
}
