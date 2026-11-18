import type { Me } from "./types";

/** Only same-site relative paths are allowed as post-login destinations (no open redirects). */
export function safeNextPath(next: string | null | undefined): string | null {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return null;
  if (next.startsWith("/login") || next.startsWith("/register")) return null;
  return next;
}

/** Where to send a user after login/registration. */
export function landingPath(me: Me, next?: string | null): string {
  if (me.user.must_change_password) return "/profile?force=1";
  if (!me.active_shop_id) return "/shops";
  return safeNextPath(next) ?? "/dashboard";
}
