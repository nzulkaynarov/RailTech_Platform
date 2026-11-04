import { defineConfig, devices } from '@playwright/test';

/**
 * CAT-CARD-2 · карточка товара в кабинете на dev-сборке с моком (MSW): 1440 и 390 px, axe и горизонтальная прокрутка; снимки и сводка
 * axe — в docs/screens/CAT-CARD-2 (E2E_SCREENS_DIR). Без стенда. Запуск из apps/cabinet:
 *
 *   npm run test:e2e:cat-card
 */
const PORT = Number(process.env.E2E_CAT_CARD_PORT ?? 5192);

export default defineConfig({
  testDir: './e2e',
  testMatch: /cat-card-2\.spec\.ts$/,
  workers: 1,
  timeout: 240_000,
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
