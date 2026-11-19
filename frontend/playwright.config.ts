import { defineConfig, devices } from "@playwright/test";

/**
 * Browser end-to-end tests. They run against a DISPOSABLE stack only:
 *   1. backend:  .venv\Scripts\python -m scripts.e2e_stack      (throwaway PostgreSQL + API on :8000)
 *   2. frontend: npm run build && npx next start -p 3000 -H 127.0.0.1
 *   3. here:     npm run e2e
 * Locally the installed Microsoft Edge is used (no browser download); set PW_CHANNEL="" to use
 * Playwright's bundled Chromium (CI installs it with `npx playwright install chromium`).
 */
const channel = process.env.PW_CHANNEL ?? "msedge";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  timeout: 60_000,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    ...(channel ? { channel } : {}),
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Edge"], ...(channel ? { channel } : {}) }, testIgnore: /mobile\.spec\.ts/ },
    { name: "mobile", use: { viewport: { width: 360, height: 740 }, isMobile: true, hasTouch: true }, testMatch: /mobile\.spec\.ts/ },
  ],
});
