import { describe, expect, it } from "vitest";
import {
  MAX_PAISE,
  catalogPermissions,
  changedFields,
  displayName,
  formatPaise,
  formatQuantity,
  isValidBarcode,
  paiseToRupeeInput,
  parseQuantity,
  parseRupeesToPaise,
  productQuery,
} from "./catalog";
import { CODE_FIELDS, errorMessage, formErrors } from "./errors";
import { ApiError } from "./api";
import { translate } from "./i18n/dictionaries";

describe("formatPaise (integer arithmetic, Indian grouping)", () => {
  it.each([
    [0, "₹0"],
    [4400, "₹44"],
    [4450, "₹44.50"],
    [5, "₹0.05"],
    [12345650, "₹1,23,456.50"],
    [100000000, "₹10,00,000"],
    [-2500, "−₹25"],
  ])("%d -> %s", (paise, expected) => expect(formatPaise(paise)).toBe(expected));

  it("handles missing and unsafe values", () => {
    expect(formatPaise(null)).toBe("—");
    expect(formatPaise(undefined)).toBe("—");
    expect(formatPaise(1.5)).toBe("—");
  });
});

describe("parseRupeesToPaise (no floating point)", () => {
  it.each([
    ["44", 4400],
    ["44.5", 4450],
    ["44.50", 4450],
    ["0.05", 5],
    ["1,200.00", 120000],
    ["₹ 30", 3000],
    ["0", 0],
    // Classic float traps: 0.1 + 0.2, 1.005 * 100, 19.99 * 100
    ["0.3", 30],
    ["19.99", 1999],
    ["1.01", 101],
  ])("%s -> %d", (input, paise) => expect(parseRupeesToPaise(input)).toEqual({ ok: true, value: paise }));

  it.each(["abc", "44.505", "-5", "4.4.4", "1e3", "44."])("rejects %s", (input) =>
    expect(parseRupeesToPaise(input)).toEqual({ ok: false, error: "invalid" }),
  );

  it("required vs optional blanks", () => {
    expect(parseRupeesToPaise("  ")).toEqual({ ok: false, error: "required" });
    expect(parseRupeesToPaise("", { required: false })).toEqual({ ok: true, value: null });
  });

  it("caps at the largest exact JavaScript integer", () => {
    expect(parseRupeesToPaise("90071992547409.91")).toEqual({ ok: true, value: MAX_PAISE });
    expect(parseRupeesToPaise("90071992547409.92")).toEqual({ ok: false, error: "too_large" });
  });

  it("round-trips through the input formatter", () => {
    for (const paise of [0, 5, 50, 4400, 4450, 123456789]) {
      expect(parseRupeesToPaise(paiseToRupeeInput(paise))).toEqual({ ok: true, value: paise });
    }
  });
});

describe("parseQuantity", () => {
  it("accepts up to 3 decimals for decimal units and normalises", () => {
    expect(parseQuantity("2.500", { allowsDecimal: true })).toEqual({ ok: true, value: "2.5" });
    expect(parseQuantity("2.125", { allowsDecimal: true })).toEqual({ ok: true, value: "2.125" });
    expect(parseQuantity("30.000", { allowsDecimal: false })).toEqual({ ok: true, value: "30" });
    expect(parseQuantity("", { allowsDecimal: true })).toEqual({ ok: true, value: null });
  });
  it("rejects fractions for count units and malformed input", () => {
    expect(parseQuantity("1.5", { allowsDecimal: false })).toEqual({ ok: false, error: "decimal_not_allowed" });
    expect(parseQuantity("1.2345", { allowsDecimal: true })).toEqual({ ok: false, error: "invalid" });
    expect(parseQuantity("-1", { allowsDecimal: true })).toEqual({ ok: false, error: "invalid" });
    expect(parseQuantity("", { allowsDecimal: true, required: true })).toEqual({ ok: false, error: "required" });
  });
  it("formats backend quantities for display", () => {
    expect(formatQuantity("30.000")).toBe("30");
    expect(formatQuantity("2.500")).toBe("2.5");
    expect(formatQuantity(null)).toBe("—");
  });
});

describe("catalogPermissions mirrors backend roles", () => {
  it("owner and admin have full access; staff view only; no role nothing", () => {
    expect(catalogPermissions("owner")).toEqual({ view: true, viewCosts: true, manage: true, managePrices: true });
    expect(catalogPermissions("admin")).toEqual({ view: true, viewCosts: true, manage: true, managePrices: true });
    expect(catalogPermissions("staff")).toEqual({ view: true, viewCosts: false, manage: false, managePrices: false });
    expect(catalogPermissions(undefined)).toEqual({ view: false, viewCosts: false, manage: false, managePrices: false });
  });
});

describe("productQuery", () => {
  it("builds the list query and never includes a shop id", () => {
    const q = new URLSearchParams(productQuery({ q: "  cheeni  ", categoryId: "c1", includeArchived: true, offset: 50 }));
    expect(q.get("q")).toBe("cheeni");
    expect(q.get("category_id")).toBe("c1");
    expect(q.get("include_archived")).toBe("true");
    expect(q.get("limit")).toBe("50");
    expect(q.get("offset")).toBe("50");
    expect(q.has("shop_id")).toBe(false);
  });
  it("omits blank filters and trims long searches to 120 chars", () => {
    const q = new URLSearchParams(productQuery({ q: "   " }));
    expect(q.has("q")).toBe(false);
    expect(q.has("include_archived")).toBe(false);
    expect(new URLSearchParams(productQuery({ q: "x".repeat(200) })).get("q")).toHaveLength(120);
  });
});

describe("misc helpers", () => {
  it("barcode rule mirrors backend", () => {
    expect(isValidBarcode("")).toBe(true);
    expect(isValidBarcode("8901234567890")).toBe(true);
    expect(isValidBarcode("890 123")).toBe(false);
    expect(isValidBarcode("x".repeat(65))).toBe(false);
  });
  it("display name prefers the Hindi name only in the Hindi UI", () => {
    const p = { name: "Sugar", name_hi: "चीनी" };
    expect(displayName(p, "hi")).toBe("चीनी");
    expect(displayName(p, "hinglish")).toBe("Sugar");
    expect(displayName({ name: "Rice", name_hi: null }, "hi")).toBe("Rice");
  });
  it("changedFields returns only edited fields", () => {
    expect(changedFields({ a: 1, b: "x", c: null }, { a: 1, b: "y", c: null })).toEqual({ b: "y" });
  });
});

describe("catalogue error mapping", () => {
  const t = (key: Parameters<typeof translate>[1]) => translate("en", key);
  it("translates catalogue codes and attaches them to fields", () => {
    const err = new ApiError(409, "PRODUCT_NAME_TAKEN", "A product with this name already exists.");
    expect(errorMessage(err, t)).toBe(translate("en", "error.productNameTaken"));
    expect(formErrors(err, t)).toEqual({ name: translate("en", "error.productNameTaken") });
    expect(CODE_FIELDS.BARCODE_RESERVED_BY_ARCHIVED).toBe("barcode");
  });
  it("404s get a generic not-found message (no existence leak wording)", () => {
    expect(errorMessage(new ApiError(404, "NOT_FOUND", "Product not found."), t)).toBe(translate("en", "error.notFound"));
  });
});
