import { defineConfig, devices } from '@playwright/test';

/**
 * E2E против vite dev сервера с ЗАМОКАННЫМ API (`page.route`) — без стенда и без Docker (FIX-44).
 * Берёт только `*.mocked.spec.ts`; обычный `playwright.config.ts` эти файлы не запускает, а
 * остальные e2e ходят на стенд и здесь не участвуют.
 *
 *   cd apps/erp/frontend && npx playwright test -c playwright.mocked.config.ts
 */
const PORT = Number(process.env.E2E_MOCK_PORT || 5199);

export default defineConfig({
	testDir: './e2e',
	testMatch: /.*\.mocked\.spec\.ts/,
	timeout: 60_000,
	expect: { timeout: 10_000 },
	fullyParallel: true,
	retries: 0,
	reporter: 'list',
	use: { baseURL: `http://localhost:${PORT}`, trace: 'retain-on-failure' },
	webServer: {
		command: `npx vite --port ${PORT} --strictPort`,
		url: `http://localhost:${PORT}`,
		reuseExistingServer: false,
		timeout: 120_000,
	},
	projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
