import { type APIRequestContext, type BrowserContext, expect } from "@playwright/test";
import { randomBytes, randomUUID } from "node:crypto";

/** Throwaway credentials per run (disposable stack only; never reused or printed). */
export const password = () => `Kirana-${randomBytes(9).toString("base64url")}`;
export const phone = () => `9${Math.floor(100_000_000 + Math.random() * 899_999_999)}`;
export const idem = () => ({ "Idempotency-Key": randomUUID() });

/** English UI for stable selectors (the language choice lives in localStorage). */
export async function useEnglish(context: BrowserContext) {
  await context.addInitScript(() => {
    try {
      window.localStorage.setItem("munim.language", "en");
    } catch {
      /* storage unavailable */
    }
  });
}

/** Register + create a shop through the API; the session cookie lands in the browser context. */
export async function ownerWithShop(request: APIRequestContext, shopName = "E2E Kirana") {
  const pw = password();
  const ph = phone();
  const reg = await request.post("/api/v1/auth/register", { data: { phone: ph, name: "E2E Owner", password: pw } });
  expect(reg.status()).toBe(201);
  const shop = await request.post("/api/v1/shops", { data: { name: shopName }, headers: idem() });
  expect(shop.status()).toBe(201);
  return { phone: ph, password: pw };
}

/** Owner adds a staff member; the staff context logs in and replaces the temporary password. */
export async function staffSession(owner: APIRequestContext, staff: APIRequestContext) {
  const ph = phone();
  const temp = password();
  const added = await owner.post("/api/v1/shops/current/members", {
    data: { phone: ph, role: "staff", name: "E2E Staff", temporary_password: temp },
    headers: idem(),
  });
  expect(added.status()).toBe(201);
  expect((await staff.post("/api/v1/auth/login", { data: { phone: ph, password: temp } })).status()).toBe(200);
  const changed = await staff.post("/api/v1/auth/change-password", { data: { current_password: temp, new_password: password() } });
  expect(changed.ok()).toBeTruthy();
}
