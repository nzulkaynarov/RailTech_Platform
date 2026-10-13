import { existsSync } from "node:fs";

import { defineConfig, devices } from "@playwright/test";

// E2E против запущенных API и фронта (CI job `e2e` или `make test-e2e-local`).
const preinstalled = "/opt/pw-browsers/chromium";
const launch =
  existsSync(preinstalled) && !process.env["CI"]
    ? { launchOptions: { executablePath: preinstalled } }
    : {};

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: process.env["CI"] ? 1 : 0,
  workers: 1,
  reporter: process.env["CI"] ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env["BASE_URL"] ?? "http://localhost:4173",
    trace: "retain-on-failure",
    locale: "ru-RU",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], ...launch },
    },
    {
      name: "mobile",
      use: { ...devices["Pixel 7"], viewport: { width: 390, height: 844 }, ...launch },
    },
  ],
});
