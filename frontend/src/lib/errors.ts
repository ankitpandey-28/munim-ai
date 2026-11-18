import { ApiError } from "./api";
import type { MessageKey } from "./i18n/dictionaries";

/** User-facing message for any error: known codes are translated; otherwise the backend's
 *  safe message is shown (it never contains secrets or stack traces). */
const CODE_MESSAGES: Partial<Record<string, MessageKey>> = {
  NETWORK_ERROR: "error.network",
  INTERNAL_ERROR: "error.generic",
  VERSION_CONFLICT: "shop.versionConflict",
};

export function errorMessage(error: unknown, t: (key: MessageKey) => string): string {
  if (error instanceof ApiError) {
    const key = CODE_MESSAGES[error.code];
    if (key) return t(key);
    return error.message || t("error.generic");
  }
  return t("error.generic");
}
