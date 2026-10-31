import { defineConfig, devices } from '@playwright/test';

/**
 * CAB-FIX-2 · все экраны кабинета на dev-сборке с моком (MSW): роли actor и viewer, 1440 и 390 px, axe и горизонтальная
 * прокрутка на каждом; снимки ключевых экранов, uz / en и тема Mini App (светлая и тёмная) — в docs/screens/cab-fix-2
 * (E2E_SCREENS_DIR), сводка — axe-summary.json там же. Без стенда. Запуск из apps/cabinet:
 *
 *   npm run test:e2e:screens
 */
const PORT = Number(process.env.E2E_SCREENS_PORT ?? 5191);

export default defineConfig({
  testDir: './e2e',
  testMatch: /screens-mock\.spec\.ts$/,
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
