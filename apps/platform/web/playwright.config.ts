import { existsSync } from "node:fs";

import { defineConfig, devices } from "@playwright/test";

// E2E на MSW: dev-сервер vite в режиме mock (VITE_API_MOCKING=true) отвечает за BFF, стенд и бэкенды не нужны.
// BASE_URL задан — тесты идут против готового адреса (стенд), сервер не поднимается; без стенда
// сценарии, зависящие от MSW, пропускаются самим тестом.
// Порт dev-сервера — E2E_PORT (по умолчанию 4173): параллельные worktree запускают e2e на разных портах.
const PORT = Number(process.env["E2E_PORT"] || "4173");
const preinstalled = "/opt/pw-browsers/chromium";
const launch =
  existsSync(preinstalled) && !process.env["CI"]
    ? { launchOptions: { executablePath: preinstalled } }
    : {};

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  // Медленный раннер CI: dev-сервер vite отдаёт antd несобранным, ленивые модули и Drawer успевают позже 5 секунд.
  expect: { timeout: 10_000 },
  retries: process.env["CI"] ? 1 : 0,
  // CI: два воркера — набор вырос (волна 13), на одном не укладывался в timeout задания; локально — один (стабильные снимки).
  workers: process.env["CI"] ? 2 : 1,
  reporter: process.env["CI"] ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env["BASE_URL"] ?? `http://localhost:${String(PORT)}`,
    trace: "retain-on-failure",
    locale: "ru-RU",
    // Тема читает prefers-reduced-motion (theme.ts → token.motion = false): antd без анимаций, axe не ловит полупрозрачные
    // меню, модалки и Drawer посреди перехода. Продукт не меняется — так он ведёт себя у пользователя с этой настройкой ОС.
    reducedMotion: "reduce",
  },
  webServer: process.env["BASE_URL"]
    ? undefined
    : {
        command: `pnpm exec vite --mode mock --port ${String(PORT)} --strictPort`,
        url: `http://localhost:${String(PORT)}`,
        // MSW включается здесь, а не в .env.mock: не зависит от файла, который легко потерять из-за .gitignore (.env.*).
        env: { VITE_API_MOCKING: "true" },
        // Чужой vite (другой worktree на том же порту) не подхватываем: занятый порт — ошибка. Явно: E2E_REUSE_SERVER=1.
        reuseExistingServer: process.env["E2E_REUSE_SERVER"] === "1",
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
