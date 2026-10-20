import { test, expect, type ConsoleMessage } from '@playwright/test';
import { DEAL_ID, mockQuoteBuilderApi } from './mocks/quoteBuilderApi';

/**
 * FIX-44 (F-7) — экран КП против замоканного API (без стенда):
 *   • на 390 px нет «Maximum update depth exceeded» (консоль и pageerror);
 *   • роль без quote.build не запрашивает предпросмотр согласования и не получает тост.
 */
const SELLER = ['quote.build', 'deal.manage'];
const OBSERVER: string[] = [];

function watchErrors(page: import('@playwright/test').Page) {
	const problems: string[] = [];
	page.on('console', (m: ConsoleMessage) => {
		if (m.type() === 'error' || m.type() === 'warning') problems.push(`${m.type()}: ${m.text()}`);
	});
	page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
	return problems;
}

for (const viewport of [{ width: 390, height: 844 }, { width: 1440, height: 900 }]) {
	test(`КП без цикла рендера, ${viewport.width} px`, async ({ page }) => {
		test.setTimeout(90_000);
		await page.setViewportSize(viewport);
		const problems = watchErrors(page);
		await mockQuoteBuilderApi(page, { permissions: SELLER, itemCount: 80 });
		await page.goto(`/#deal-quote/${DEAL_ID}`);
		await expect(page.getByRole('textbox', { name: 'Кол-во' }).first()).toBeVisible({ timeout: 30_000 });
		await page.waitForTimeout(1500);
		await page.screenshot({ path: `../../../docs/screens/fix-44/quote-${viewport.width}.png` });
		const depth = problems.filter((p) => /Maximum update depth/i.test(p));
		expect(depth.map((p) => p.slice(0, 300))).toEqual([]);
	});
}

test('роль без quote.build: предпросмотр согласования не запрашивается, тоста нет', async ({ page }) => {
	await page.setViewportSize({ width: 390, height: 844 });
	const problems = watchErrors(page);
	const api = await mockQuoteBuilderApi(page, { permissions: OBSERVER });
	await page.goto(`/#deal-quote/${DEAL_ID}`);
	await expect(page.getByRole('textbox', { name: 'Кол-во' }).first()).toBeVisible({ timeout: 30_000 });
	await page.waitForTimeout(1000);
	expect(api.requests.filter((r) => r.includes('approval-preview'))).toEqual([]);
	await expect(page.getByText('Недостаточно прав')).toHaveCount(0);
	expect(problems.filter((p) => /403|Maximum update depth/i.test(p))).toEqual([]);
});
