import { existsSync } from "node:fs";

import { defineConfig, devices } from "@playwright/test";

// E2E на MSW: dev-сервер vite в режиме mock (`.env.mock`) отвечает за BFF, стенд и бэкенды не нужны.
// BASE_URL задан — тесты идут против готового адреса (стенд), сервер не поднимается; без стенда
// сценарии, зависящие от MSW, пропускаются самим тестом.
const PORT = 4173;
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
    baseURL: process.env["BASE_URL"] ?? `http://localhost:${String(PORT)}`,
    trace: "retain-on-failure",
    locale: "ru-RU",
  },
  webServer: process.env["BASE_URL"]
    ? undefined
    : {
        command: `pnpm exec vite --mode mock --port ${String(PORT)} --strictPort`,
        url: `http://localhost:${String(PORT)}`,
        reuseExistingServer: !process.env["CI"],
        timeout: 60_000,
      },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 }, ...launch },
    },
    {
      name: "mobile",
      use: { ...devices["Pixel 7"], viewport: { width: 390, height: 844 }, ...launch },
    },
  ],
});
