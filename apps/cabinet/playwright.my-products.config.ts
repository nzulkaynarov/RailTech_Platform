import { defineConfig, devices } from '@playwright/test';

/**
 * PART-2 · «Мои товары» на dev-сборке с моком (MSW), без стенда: снимки 1440 и 390 px и axe в docs/screens/PART-2
 * (E2E_SCREENS_DIR). Запуск из apps/cabinet:
 *
 *   E2E_SCREENS_DIR=../../../../docs/screens/PART-2 npm run test:e2e:my-products
 */
const PORT = Number(process.env.E2E_SCREENS_PORT ?? 5193);

export default defineConfig({
  testDir: './e2e',
  testMatch: /my-products-screens\.spec\.ts$/,
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
