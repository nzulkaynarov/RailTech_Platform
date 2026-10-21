import { defineConfig, devices } from '@playwright/test';

/**
 * Прогон M2 на стенде ансамбля (FIX-51): Cabinet против настоящего ERP, не MSW.
 * Не входит ни в vitest (`exclude: e2e/**`), ни в tsc, ни в CI — запуск вручную:
 *
 *   E2E_BASE_URL=http://cabinet.localhost:8088 \
 *   E2E_STAND_ROOT=<корень репозитория со стендом и .env> \
 *   E2E_CRM_ADMIN_EMAIL=… E2E_CRM_ADMIN_PASSWORD=… \
 *   npm run test:e2e
 *
 * Переменные окружения и порядок — в шапке e2e/gate-m2.spec.ts. Пароли и токены — только из окружения.
 */
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://cabinet.localhost:8088';

export default defineConfig({
  testDir: './e2e',
  testMatch: /gate-m2\.spec\.ts$/,
  // Один сценарий на всю цепочку (лид → КП → договор → счёт → поставка → акт): шаги зависят друг от друга.
  workers: 1,
  fullyParallel: false,
  timeout: 180_000,
  expect: { timeout: 15_000 },
  reporter: [['list']],
  outputDir: 'test-results',
  use: {
    baseURL: BASE_URL,
    locale: 'ru-RU',
    timezoneId: 'Asia/Tashkent',
    viewport: { width: 1440, height: 900 },
    // без таймаутов действий зависшая страница держала бы шаг до таймаута всего теста
    actionTimeout: 30_000,
    navigationTimeout: 45_000,
    trace: 'off',
    screenshot: 'off',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
});
