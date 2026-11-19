import { expect, test } from "@playwright/test";
import { idem, ownerWithShop, staffSession, useEnglish } from "./helpers";

const COST_PAISE = 3917; // distinctive: must never reach a staff browser

test("owner manages categories, products, prices, aliases and archive through the UI", async ({ page, context }) => {
  await useEnglish(context);
  await ownerWithShop(context.request);
  // Next keeps the previous route mounted but hidden (<Activity>): only act on visible fields.
  const label = (name: string) => page.getByLabel(name).filter({ visible: true });

  // Empty catalogue
  await page.goto("/catalog");
  await expect(page.getByRole("heading", { name: "Products and categories" })).toBeVisible();
  await expect(page.getByText("No products yet")).toBeVisible();

  // Category
  await page.getByRole("link", { name: "Categories" }).click();
  await expect(page).toHaveURL(/\/catalog\/categories$/);
  await label("Category name").fill("Grocery");
  await label("Hindi name").fill("किराना");
  await page.getByRole("button", { name: "Add category" }).click();
  await expect(page.getByText("Category added.")).toBeVisible();
  await expect(page.getByTestId("category-list")).toContainText("Grocery");

  // Duplicate category name → friendly error
  await label("Category name").fill("grocery");
  await page.getByRole("button", { name: "Add category" }).click();
  await expect(page.getByText("A category with this name already exists.").first()).toBeVisible();

  // Product: client-side validation first (nothing is sent)
  await page.getByRole("link", { name: "Products", exact: true }).first().click();
  await page.getByRole("button", { name: "+ Add product" }).click();
  await label("Product name").fill("Sugar");
  await label("Selling price (₹)").fill("abc");
  await page.getByRole("button", { name: "Add product", exact: true }).click();
  await expect(page.getByText("Enter a valid amount in rupees").first()).toBeVisible();

  // Loose product needs a decimal unit
  await label("Unit").selectOption("piece");
  await label("Sold loose (weighed or measured)").check();
  await label("Selling price (₹)").fill("44.50");
  await page.getByRole("button", { name: "Add product", exact: true }).click();
  await expect(page.getByText("Loose items need a unit that allows decimals").first()).toBeVisible();

  // Valid product
  await label("Hindi name").fill("चीनी");
  await label("Category").first().selectOption({ label: "Grocery" });
  await label("Unit").selectOption("kg");
  await label("Cost price (₹)").fill((COST_PAISE / 100).toFixed(2));
  await label("Reorder level (kg)").fill("5");
  await page.getByRole("textbox", { name: /^Barcode/ }).filter({ visible: true }).fill("8901000000024");
  await page.getByRole("button", { name: "Add product", exact: true }).click();
  await expect(page.getByText("Product added.")).toBeVisible();
  const list = page.getByTestId("product-list");
  await expect(list).toContainText("Sugar");
  await expect(list).toContainText("₹44.50");
  await expect(list).toContainText("Loose");

  // Detail: alias
  await list.getByRole("link", { name: /Sugar/ }).click();
  await expect(page.getByRole("heading", { name: "Sugar" })).toBeVisible();
  await label("New other name").fill("Cheeni");
  await page.getByRole("button", { name: "Add name" }).click();
  await expect(page.getByTestId("alias-list")).toContainText("Cheeni");

  // Price change requires an explicit confirmation step
  await page.getByRole("button", { name: "Update prices" }).click();
  await label("Selling price (₹)").fill("46");
  await page.getByRole("button", { name: "Update prices" }).click();
  await expect(page.getByText("Please check the new prices before saving:")).toBeVisible();
  await expect(page.getByText("₹44.50 →")).toBeVisible();
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByText("Prices updated.")).toBeVisible();
  await expect(page.getByTestId("selling-price")).toContainText("₹46");
  await expect(page.getByTestId("price-history").locator("li")).toHaveCount(3); // initial selling + cost, new selling

  // Edit details (no prices here)
  await page.getByRole("button", { name: "Edit" }).click();
  await label("Reorder level (kg)").fill("10");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Reorder level", { exact: true }).filter({ visible: true }).locator("..")).toContainText("10 kg");

  // Search by alias and by exact barcode
  await page.getByRole("link", { name: /Back to products/ }).click();
  const search = label("Search by name, other name or barcode");
  await search.fill("CHEENI");
  await expect(list).toContainText("Sugar");
  await search.fill("8901000000024");
  await expect(list).toContainText("Sugar");
  await search.fill("zzz-nothing");
  await expect(page.getByText("No products match your search.")).toBeVisible();
  await search.fill("");

  // Archive with confirmation; hidden from list unless "Show archived"
  await list.getByRole("link", { name: /Sugar/ }).click();
  await page.getByRole("button", { name: "Archive product" }).click();
  await expect(page.getByText("Archive this product?")).toBeVisible();
  await page.getByRole("group", { name: "Archive product" }).getByRole("button", { name: "Archive product" }).click();
  await expect(page.getByText("This product is archived.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Edit" })).toHaveCount(0);
  await page.getByRole("link", { name: /Back to products/ }).click();
  await expect(page.getByText("No products yet")).toBeVisible();
  await label("Show archived").check();
  await expect(list).toContainText("Archived");

  // Persisted in PostgreSQL: a fresh page load shows the same data
  await page.reload();
  await label("Show archived").check();
  await expect(list).toContainText("Sugar");
});

test("staff sees selling prices only: no cost data in the UI or in any API response", async ({ browser }) => {
  const ownerCtx = await browser.newContext();
  await ownerWithShop(ownerCtx.request);
  const created = await ownerCtx.request.post("/api/v1/catalog/products", {
    data: { name: "Soap", base_unit_code: "piece", selling_price_paise: 3500, default_cost_price_paise: COST_PAISE },
    headers: idem(),
  });
  expect(created.status()).toBe(201);
  const product = await created.json();

  const staffCtx = await browser.newContext();
  await useEnglish(staffCtx);
  await staffSession(ownerCtx.request, staffCtx.request);
  const page = await staffCtx.newPage();
  const bodies: string[] = [];
  page.on("response", async (r) => {
    if (r.url().includes("/api/v1/catalog")) bodies.push(await r.text().catch(() => ""));
  });

  await page.goto("/catalog");
  await expect(page.getByTestId("product-list")).toContainText("Soap");
  await expect(page.getByText("Only the owner or an admin can make changes.")).toBeVisible();
  await expect(page.getByRole("button", { name: "+ Add product" })).toHaveCount(0);

  await page.getByTestId("product-list").getByRole("link", { name: /Soap/ }).click();
  await expect(page.getByTestId("selling-price")).toContainText("₹35");
  await expect(page.getByTestId("cost-price")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Update prices" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Archive product" })).toHaveCount(0);
  await expect(page.getByLabel("New other name")).toHaveCount(0);
  await expect(page.getByTestId("price-history")).not.toContainText("Cost");

  expect(bodies.length).toBeGreaterThan(0);
  for (const body of bodies) expect(body).not.toContain(String(COST_PAISE));
  expect(await page.content()).not.toContain(String(COST_PAISE));
  expect(product.id).toBeTruthy();
  await ownerCtx.close();
  await staffCtx.close();
});

test("another shop's product URL shows not-found, revealing nothing", async ({ browser }) => {
  const a = await browser.newContext();
  await ownerWithShop(a.request, "Shop A");
  const created = await a.request.post("/api/v1/catalog/products", {
    data: { name: "Secret Basmati", base_unit_code: "kg", selling_price_paise: 9900 },
    headers: idem(),
  });
  const { id } = await created.json();

  const b = await browser.newContext();
  await useEnglish(b);
  await ownerWithShop(b.request, "Shop B");
  const page = await b.newPage();
  await page.goto(`/catalog/${id}`);
  await expect(page.getByText("Not found. It may have been removed.")).toBeVisible();
  await expect(page.locator("body")).not.toContainText("Secret Basmati");
  await a.close();
  await b.close();
});

test("logged-out visitor is sent to login", async ({ page }) => {
  await page.goto("/catalog");
  await expect(page).toHaveURL(/\/login\?next=%2Fcatalog/);
});
