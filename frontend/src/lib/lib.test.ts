import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiFetch, parseError } from "./api";
import { errorMessage } from "./errors";
import { dictionaries, translate } from "./i18n/dictionaries";
import { landingPath, safeNextPath } from "./redirects";
import type { Me } from "./types";
import { isValidPincode, normalizeIndianMobile, passwordIssues } from "./validation";

describe("normalizeIndianMobile (mirrors backend)", () => {
  it.each([
    ["9876543210", "+919876543210"],
    ["+91 98765-43210", "+919876543210"],
    ["09876543210", "+919876543210"],
    ["919876543210", "+919876543210"],
    ["00919876543210", "+919876543210"],
  ])("%s -> %s", (raw, expected) => expect(normalizeIndianMobile(raw)).toBe(expected));

  it.each(["", "12345", "+14155550100", "5876543210", "98x6543210"])("rejects %s", (raw) =>
    expect(normalizeIndianMobile(raw)).toBeNull(),
  );
});

describe("validation", () => {
  it("password issues", () => {
    expect(passwordIssues("short")).toContain("too_short");
    expect(passwordIssues("9876543210", "+919876543210")).toContain("same_as_phone");
    expect(passwordIssues("Kirana-Strong-1")).toEqual([]);
  });
  it("pincode", () => {
    expect(isValidPincode("141001")).toBe(true);
    expect(isValidPincode("041001")).toBe(false);
    expect(isValidPincode("1410")).toBe(false);
  });
});

describe("redirects", () => {
  it("only allows same-site relative paths", () => {
    expect(safeNextPath("/settings")).toBe("/settings");
    expect(safeNextPath("//evil.example")).toBeNull();
    expect(safeNextPath("https://evil.example")).toBeNull();
    expect(safeNextPath("/\\evil.example")).toBeNull();
    expect(safeNextPath("/login")).toBeNull();
  });
  it("landing path follows session state", () => {
    const base: Me = {
      user: { id: "u", phone: "+919876543210", name: "R", preferred_language: "hinglish", must_change_password: false, created_at: "" },
      active_shop_id: "s",
      memberships: [],
    };
    expect(landingPath(base, "/settings")).toBe("/settings");
    expect(landingPath({ ...base, active_shop_id: null })).toBe("/shops");
    expect(landingPath({ ...base, user: { ...base.user, must_change_password: true } })).toBe("/profile?force=1");
  });
});

describe("api client", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("parses the backend error envelope", async () => {
    const response = new Response(
      JSON.stringify({
        error: { code: "VALIDATION_ERROR", message: "Request validation failed.", details: [{ loc: ["body", "phone"], msg: "bad", type: "value_error" }], request_id: "rid-1" },
      }),
      { status: 422, headers: { "content-type": "application/json" } },
    );
    const err = await parseError(response);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("VALIDATION_ERROR");
    expect(err.requestId).toBe("rid-1");
    expect(err.fieldErrors()).toEqual({ phone: "bad" });
  });

  it("falls back safely for non-JSON errors", async () => {
    const err = await parseError(new Response("<html>oops</html>", { status: 502 }));
    expect(err.code).toBe("HTTP_502");
    expect(err.message).not.toContain("<html>");
  });

  it("sends same-origin requests with an Idempotency-Key when asked", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await apiFetch("/shops", { method: "POST", body: { name: "A" }, idempotencyKey: "key-12345678" });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/shops");
    expect(init.credentials).toBe("same-origin");
    expect((init.headers as Record<string, string>)["Idempotency-Key"]).toBe("key-12345678");
  });

  it("maps network failures to NETWORK_ERROR and 401 to unauthenticated", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    await expect(apiFetch("/auth/me")).rejects.toMatchObject({ code: "NETWORK_ERROR" });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: { code: "AUTHENTICATION_REQUIRED", message: "Please log in." } }), { status: 401 })));
    const err = (await apiFetch("/auth/me").catch((e: unknown) => e)) as ApiError;
    expect(err.isUnauthenticated).toBe(true);
  });

  it("user-facing messages are translated for known codes", () => {
    const t = (key: Parameters<typeof translate>[1]) => translate("hinglish", key);
    expect(errorMessage(new ApiError(0, "NETWORK_ERROR", "x"), t)).toBe(translate("hinglish", "error.network"));
    expect(errorMessage(new ApiError(403, "PERMISSION_DENIED", "Not allowed."), t)).toBe(translate("hinglish", "error.permission"));
    // Unmapped codes fall back to the backend's safe message.
    expect(errorMessage(new ApiError(409, "SOME_NEW_CODE", "Backend message."), t)).toBe("Backend message.");
    expect(errorMessage(new Error("boom"), t)).toBe(translate("hinglish", "error.generic"));
  });
});

describe("i18n dictionaries", () => {
  const keys = Object.keys(dictionaries.en).sort();
  it.each(Object.keys(dictionaries))("%s defines every key with a non-empty string", (lang) => {
    const dict = dictionaries[lang as keyof typeof dictionaries];
    expect(Object.keys(dict).sort()).toEqual(keys);
    for (const value of Object.values(dict)) expect(value.trim().length).toBeGreaterThan(0);
  });
  it("never labels a metric 'kamai' (BR-TERM-01)", () => {
    for (const dict of Object.values(dictionaries)) {
      for (const value of Object.values(dict)) expect(value.toLowerCase()).not.toContain("kamai");
    }
  });
});
