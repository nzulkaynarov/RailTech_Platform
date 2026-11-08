import { defineConfig, devices } from '@playwright/test';

/**
 * FX-4 · смена банковских реквизитов в кабинете на dev-сборке с моком (MSW): снимки 1440 и 390 px и axe в docs/screens/fx-4
 * (E2E_SCREENS_DIR). Запуск из apps/cabinet: E2E_SCREENS_DIR=../../../../docs/screens/fx-4 npx playwright test -c playwright.fx-4.config.ts
 */
const PORT = Number(process.env.E2E_SCREENS_PORT ?? 5195);

export default defineConfig({
  testDir: './e2e',
  testMatch: /fx-4-bank-change\.spec\.ts$/,
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
