import { expect, test } from "@playwright/test";
import { idem, ownerWithShop, useEnglish } from "./helpers";

test("catalogue screens fit a 360px phone without horizontal scrolling", async ({ page, context }) => {
  await useEnglish(context);
  await ownerWithShop(context.request);
  const r = await context.request.post("/api/v1/catalog/products", {
    data: { name: "Toor Dal (premium, 1 kg pouch)", base_unit_code: "packet", selling_price_paise: 18950, barcode: "8901234567890123" },
    headers: idem(),
  });
  const { id } = await r.json();
  for (const path of ["/catalog", "/catalog/categories", `/catalog/${id}`]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: "Products and categories" })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `horizontal overflow on ${path}`).toBeLessThanOrEqual(0);
  }
  // Touch targets: primary buttons are at least 44px tall
  await page.goto("/catalog");
  const box = await page.getByRole("button", { name: "+ Add product" }).boundingBox();
  expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
});
