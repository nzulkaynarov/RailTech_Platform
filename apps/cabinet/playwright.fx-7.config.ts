import { defineConfig, devices } from '@playwright/test';

/**
 * FX-7 · заказы и запросы цен партнёра на dev-сборке с моком (MSW): снимки 1440 и 390 px и axe в docs/screens/fx-7
 * (E2E_SCREENS_DIR). Запуск из apps/cabinet: E2E_SCREENS_DIR=../../../../docs/screens/fx-7 npx playwright test -c playwright.fx-7.config.ts
 */
const PORT = Number(process.env.E2E_SCREENS_PORT ?? 5197);

export default defineConfig({
  testDir: './e2e',
  testMatch: /fx-7-partner-orders\.spec\.ts$/,
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 10_000 },
  reporter: [['list']],
  outputDir: 'test-results',
  use: {
    baseURL: `http://localhost:${PORT}`,
    locale: 'ru-RU',
    timezoneId: 'Asia/Tashkent',
    viewport: { width: 1440, height: 900 },
    launchOptions: { executablePath: process.env.E2E_CHROMIUM_PATH || undefined },
    trace: 'off',
    screenshot: 'off',
  },
  webServer: {
    command: `VITE_PORTAL_MOCK=1 VITE_BOT_USERNAME=railtech_bot npx vite --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}/login`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
});
