import { defineConfig, devices } from '@playwright/test';

/**
 * Публичные экраны входа (D1-9): `/login`, `/login/sent`, `/new-client` на dev-сборке с моком (MSW) — без стенда.
 * Снимки 1440 и 390 px и axe — в docs/screens/w16-d1-9 (E2E_SCREENS_DIR). Запуск из apps/cabinet:
 *
 *   npm run test:e2e:public
 */
const PORT = Number(process.env.E2E_PUBLIC_PORT ?? 5189);

export default defineConfig({
  testDir: './e2e',
  testMatch: /public-pages\.spec\.ts$/,
  workers: 1,
  timeout: 60_000,
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
