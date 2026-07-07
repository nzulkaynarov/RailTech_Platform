import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright browser E2E config. OPTIONAL dev tooling — activate with:
 *   cd frontend && npm i -D @playwright/test && npx playwright install --with-deps
 *
 * Kept out of vitest (vitest.config.ts excludes e2e/**), tsc (tsconfig includes
 * only src), and eslint (ignored) so the rest of CI is unaffected until it's
 * installed. Specs live in e2e/. See Docs/dev/ops/e2e.md.
 *
 * BASE_URL points at a running app — staging once it exists, otherwise a local
 * `npm run dev` / `npm run preview`, or prod for a read-only smoke.
 */
const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:5173';

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
