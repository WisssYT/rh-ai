import { defineConfig } from "@playwright/test";

// Runs against the already-started local stack (backend :8000, worker, Vite :5173) with seeded demo data.
// PW_CHROMIUM_PATH lets you point at an existing Chromium if `npx playwright install chromium` is not possible.
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
});
