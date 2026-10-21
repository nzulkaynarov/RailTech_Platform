import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { DEAL_ID, mockRequestApi } from './mocks/requestApi';

/**
 * FIX-67 — из заявки можно сделать КП, против замоканного API (без стенда):
 *   • заявка без строк (словами): «Взять в работу» и «Создать КП», «Взять в работу и подготовить» нет;
 *   • заявка со строками: обе кнопки создания КП;
 *   • конструктор КП, пустой черновик: текст заявки раскрыт рядом, кнопка «Разобрать текст в строки (ИИ)»;
 *   • axe: 0 serious/critical на каждом экране.
 * Скриншоты в docs/screens/fix-67/ — только при `SCREENSHOTS=1`.
 */
const SHOTS = process.env.SCREENSHOTS === '1';
const SELLER = ['deal.manage', 'quote.edit_pricing', 'quote.build'];
const TEXT = 'Нужны рельсы Р65, 500 тонн, и накладки к ним. Поставка в Ташкент до конца ноября.';
const VIEWPORTS = [{ width: 1440, height: 900 }, { width: 390, height: 844 }];

async function expectNoBlockingAxe(page: Page) {
	const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
	const blocking = result.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
	expect(blocking.map((v) => `${v.id}: ${v.nodes[0]?.target?.join(' ')}`)).toEqual([]);
}

for (const viewport of VIEWPORTS) {
	test.describe(`${viewport.width} px`, () => {
		test.use({ viewport });

		test('заявка словами: «Взять в работу» и «Создать КП», без «Взять в работу и подготовить»', async ({ page }) => {
			await mockRequestApi(page, { permissions: SELLER, requestLines: 0, text: TEXT });
			await page.goto(`/#request-detail/${DEAL_ID}`);

			await expect(page.getByRole('button', { name: 'Создать КП' })).toBeVisible({ timeout: 30_000 });
			await expect(page.getByRole('button', { name: 'Взять в работу', exact: true })).toBeVisible();
			await expect(page.getByRole('button', { name: 'Взять в работу и подготовить КП' })).toHaveCount(0);
			await expect(page.getByText(TEXT)).toBeVisible();
			if (SHOTS) await page.screenshot({ path: `../../../docs/screens/fix-67/request-words-${viewport.width}.png`, fullPage: true });
			await expectNoBlockingAxe(page);
		});

		test('заявка со строками: «Создать КП» и «Взять в работу и подготовить КП»', async ({ page }) => {
			await mockRequestApi(page, { permissions: SELLER, requestLines: 3 });
			await page.goto(`/#request-detail/${DEAL_ID}`);

			await expect(page.getByRole('button', { name: 'Создать КП' })).toBeVisible({ timeout: 30_000 });
			await expect(page.getByRole('button', { name: 'Взять в работу и подготовить КП' })).toBeVisible();
			if (SHOTS) await page.screenshot({ path: `../../../docs/screens/fix-67/request-lines-${viewport.width}.png`, fullPage: true });
			await expectNoBlockingAxe(page);
		});

		test('без права на цены: ни «Создать КП», ни «Взять в работу и подготовить»', async ({ page }) => {
			await mockRequestApi(page, { permissions: ['deal.manage'], requestLines: 3 });
			await page.goto(`/#request-detail/${DEAL_ID}`);

			await expect(page.getByRole('button', { name: 'Взять в работу', exact: true })).toBeVisible({ timeout: 30_000 });
			await expect(page.getByRole('button', { name: 'Создать КП' })).toHaveCount(0);
			await expect(page.getByRole('button', { name: 'Взять в работу и подготовить КП' })).toHaveCount(0);
		});

		test('пустой черновик КП: текст заявки рядом, кнопка разбора ИИ', async ({ page }) => {
			await mockRequestApi(page, { permissions: SELLER, stage: 'CALCULATING', requestLines: 0, text: TEXT, withDraftQuote: true });
			await page.goto(`/#deal-quote/${DEAL_ID}`);

			const text = page.getByTestId('request-text');
			await expect(text).toHaveText(TEXT, { timeout: 30_000 });
			await expect(page.getByRole('button', { name: 'Разобрать текст в строки (ИИ)' })).toBeVisible();
			await page.waitForTimeout(800);
			if (SHOTS) await page.screenshot({ path: `../../../docs/screens/fix-67/draft-with-request-text-${viewport.width}.png`, fullPage: true });
			await expectNoBlockingAxe(page);
		});

		test('ИИ недоступен: понятное сообщение, а не ошибка сервера', async ({ page }) => {
			const api = await mockRequestApi(page, { permissions: SELLER, stage: 'CALCULATING', text: TEXT, withDraftQuote: true });
			await page.route('**/api/v1/sourcing/parse-request-text/', (route) =>
				route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'AI_DISABLED' }) }));
			await page.goto(`/#deal-quote/${DEAL_ID}`);

			await page.getByRole('button', { name: 'Разобрать текст в строки (ИИ)' }).click();
			await expect(page.getByText('ИИ сейчас недоступен. Наберите строки вручную по тексту заявки.')).toBeVisible();
			expect(api.posts['sourcing/parse-request-text/']).toBeUndefined(); // перехвачен вторым маршрутом
		});

		test('FIX-67b: разбор этого КП уже идёт (409) — понятное сообщение, кнопка снова доступна', async ({ page }) => {
			await mockRequestApi(page, { permissions: SELLER, stage: 'CALCULATING', text: TEXT, withDraftQuote: true });
			await page.route('**/api/v1/sourcing/parse-request-text/', (route) =>
				route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: 'PARSE_ALREADY_RUNNING' }) }));
			await page.goto(`/#deal-quote/${DEAL_ID}`);

			const parse = page.getByRole('button', { name: 'Разобрать текст в строки (ИИ)' });
			await parse.click();
			const message = page.getByText('Разбор текста этого КП уже идёт — дождитесь результата, строки появятся сами.');
			await expect(message).toBeVisible();
			await expect(parse).toBeEnabled();
			await page.waitForTimeout(600);
			if (SHOTS && viewport.width === 1440) await page.screenshot({ path: '../../../docs/screens/fix-67b/parse-already-running-1440.png' });
		});
	});
}
