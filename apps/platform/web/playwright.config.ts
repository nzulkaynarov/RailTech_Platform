import { existsSync } from "node:fs";

import { defineConfig, devices } from "@playwright/test";

// E2E на MSW: сервер отдаёт SPA в режиме mock (VITE_API_MOCKING=true), API отвечает MSW, стенд и бэкенды не нужны.
// По умолчанию (W14-S2) — СБОРКА: `vite build --mode mock` (≈1 с) и `vite preview`; сборка с NODE_ENV=development оставляет
// import.meta.env.DEV (мокирование MSW и витрина /dev/ui), но antd приходит готовыми чанками, а не россыпью модулей, которые
// dev-сервер vite преобразует на лету на каждый прогон. E2E_DEV=1 — прежний dev-сервер (отладка с HMR).
// BASE_URL задан — тесты идут против готового адреса (стенд), сервер не поднимается; без стенда
// сценарии, зависящие от MSW, пропускаются самим тестом.
// Порт сервера — E2E_PORT (по умолчанию 4173): параллельные worktree запускают e2e на разных портах.
// Мобильный проект (390) гоняет только сценарии с тегом @mobile — экраны с адаптивной логикой (нижняя панель, Drawer, список
// вместо таблицы); остальное — десктоп. Шардирование в CI — `--shard=i/N` (см. .github/workflows/ci.yml).
const PORT = Number(process.env["E2E_PORT"] || "4173");
const DEV_SERVER = process.env["E2E_DEV"] === "1";
const preinstalled = "/opt/pw-browsers/chromium";
const launch =
  existsSync(preinstalled) && !process.env["CI"]
    ? { launchOptions: { executablePath: preinstalled } }
    : {};

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  // Запас на медленный раннер CI: Drawer и ленивые чанки antd на загруженной машине успевают позже 5 секунд.
  expect: { timeout: 10_000 },
  // Повторов нет нигде: «flaky» в отчёте — это красный тест, а не зелёный (W14-S2).
  retries: 0,
  // CI: два воркера на шард; локально — один (стабильные снимки).
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
        command: DEV_SERVER
          ? `pnpm exec vite --mode mock --port ${String(PORT)} --strictPort`
          : `pnpm exec vite build --mode mock --outDir dist/e2e && pnpm exec vite preview --mode mock --outDir dist/e2e --port ${String(PORT)} --strictPort`,
        url: `http://localhost:${String(PORT)}`,
        // MSW включается здесь, а не в .env.mock: не зависит от файла, который легко потерять из-за .gitignore (.env.*).
        // NODE_ENV=development для сборки — чтобы import.meta.env.DEV оставался true (мокирование и /dev/ui); в боевой dist это не попадает.
        env: { VITE_API_MOCKING: "true", NODE_ENV: "development" },
        // Чужой сервер (другой worktree на том же порту) не подхватываем: занятый порт — ошибка. Явно: E2E_REUSE_SERVER=1.
        reuseExistingServer: process.env["E2E_REUSE_SERVER"] === "1",
        timeout: 120_000,
      },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 }, ...launch },
    },
    {
      name: "mobile",
      // Только экраны с адаптивной логикой: тег @mobile в названии теста или группы.
      grep: /@mobile/,
      use: { ...devices["Pixel 7"], viewport: { width: 390, height: 844 }, ...launch },
    },
  ],
});
