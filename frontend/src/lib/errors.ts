import { ApiError } from "./api";
import type { MessageKey } from "./i18n/dictionaries";

/** User-facing message for any error: known codes are translated; otherwise the backend's
 *  safe message is shown (it never contains secrets or stack traces). */
const CODE_MESSAGES: Partial<Record<string, MessageKey>> = {
  NETWORK_ERROR: "error.network",
  INTERNAL_ERROR: "error.generic",
  VERSION_CONFLICT: "shop.versionConflict",
  PERMISSION_DENIED: "error.permission",
  // Catalogue
  PRODUCT_NAME_TAKEN: "error.productNameTaken",
  CATEGORY_NAME_TAKEN: "error.categoryNameTaken",
  BARCODE_TAKEN: "error.barcodeTaken",
  BARCODE_RESERVED_BY_ARCHIVED: "error.barcodeArchived",
  ALIAS_EXISTS: "error.aliasExists",
  PRODUCT_ARCHIVED: "error.productArchived",
  UNIT_LOCKED: "error.unitLocked",
  STOCK_NOT_ZERO: "error.stockNotZero",
  CATEGORY_ARCHIVED: "error.categoryArchived",
  ALREADY_ARCHIVED: "error.alreadyArchived",
  CATEGORY_IN_USE: "category.inUse",
  LOOSE_REQUIRES_DECIMAL_UNIT: "error.looseUnit",
  DECIMAL_NOT_ALLOWED_FOR_UNIT: "error.quantityWhole",
};

/** Error codes whose message belongs to one form field (shown next to that field). */
export const CODE_FIELDS: Partial<Record<string, string>> = {
  PRODUCT_NAME_TAKEN: "name",
  CATEGORY_NAME_TAKEN: "name",
  BARCODE_TAKEN: "barcode",
  UNIT_LOCKED: "base_unit_code",
  STOCK_NOT_ZERO: "track_stock",
  BARCODE_RESERVED_BY_ARCHIVED: "barcode",
  ALIAS_EXISTS: "alias_text",
  INVALID_ALIAS: "alias_text",
  INVALID_UNIT: "base_unit_code",
  LOOSE_REQUIRES_DECIMAL_UNIT: "is_loose",
  DECIMAL_NOT_ALLOWED_FOR_UNIT: "reorder_level",
  INVALID_CATEGORY: "category_id",
  CATEGORY_ARCHIVED: "category_id",
};

export function errorMessage(error: unknown, t: (key: MessageKey) => string): string {
  if (error instanceof ApiError) {
    const key = CODE_MESSAGES[error.code];
    if (key) return t(key);
    if (error.status === 404) return t("error.notFound");
    return error.message || t("error.generic");
  }
  return t("error.generic");
}

/** Field errors for a form: validation details plus code-specific fields. */
export function formErrors(error: unknown, t: (key: MessageKey) => string): Record<string, string> {
  if (!(error instanceof ApiError)) return {};
  const out = error.fieldErrors();
  const field = CODE_FIELDS[error.code];
  if (field) out[field] = errorMessage(error, t);
  return out;
}
