import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { mockSetupApi } from './mocks/setupApi';

/**
 * FIX-65 — первый запуск против замоканного API (без стенда):
 *   • суперпользователь без компании видит мастер «Настройка ERP: ваша компания», а не тупик;
 *   • ошибка ИНН приходит с сервера (422) и показывается у поля; после исправления — вход в приложение;
 *   • сотрудник без компании читает, что администратор ещё не завершил настройку.
 * axe без нарушений на каждом экране; скриншоты в docs/screens/fix-65/ — только при `SCREENSHOTS=1`.
 */
const SHOTS = process.env.SCREENSHOTS === '1';
const VIEWPORTS = [{ width: 1440, height: 900 }, { width: 390, height: 844 }];

async function expectNoAxeViolations(page: Page) {
	const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
	expect(results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([]);
}

for (const viewport of VIEWPORTS) {
	test.describe(`${viewport.width} px`, () => {
		test.use({ viewport });

		test('администратор: мастер своей компании, ошибка ИНН у поля, затем вход в приложение', async ({ page }) => {
			const api = await mockSetupApi(page, { role: 'admin' });
			await page.goto('/');

			await expect(page.getByRole('heading', { name: 'Настройка ERP: ваша компания' })).toBeVisible({ timeout: 30_000 });
			await expect(page.getByText('Учётная запись не привязана к компании')).toHaveCount(0);
			if (SHOTS) await page.screenshot({ path: `../../../docs/screens/fix-65/wizard-${viewport.width}.png`, fullPage: true });
			await expectNoAxeViolations(page);

			await page.getByLabel(/Название компании/).fill('ООО Рейл');
			await page.getByLabel('ИНН').fill('12');
			await page.getByRole('button', { name: 'Создать компанию' }).click();

			await expect(page.getByText('Некорректный формат ИНН.')).toBeVisible();
			await expect(page.getByLabel('ИНН')).toHaveAttribute('aria-invalid', 'true');
			if (SHOTS) await page.screenshot({ path: `../../../docs/screens/fix-65/wizard-inn-error-${viewport.width}.png`, fullPage: true });
			await expectNoAxeViolations(page);

			await page.getByLabel('ИНН').fill('123456789');
			await page.getByRole('button', { name: 'Создать компанию' }).click();

			await expect(page.getByRole('heading', { name: 'Настройка ERP: ваша компания' })).toHaveCount(0, { timeout: 30_000 });
			expect(api.created).toHaveLength(2);
			expect(api.created[1]).toMatchObject({ name: 'ООО Рейл', inn: '123456789' });
			if (SHOTS) await page.screenshot({ path: `../../../docs/screens/fix-65/after-setup-${viewport.width}.png` });
		});

		test('сотрудник: экран «не привязана» с пояснением, что настройка не завершена', async ({ page }) => {
			await mockSetupApi(page, { role: 'staff' });
			await page.goto('/');

			await expect(page.getByText(/Администратор ещё не завершил первоначальную настройку ERP/)).toBeVisible({ timeout: 30_000 });
			await expect(page.getByRole('textbox')).toHaveCount(0);
			if (SHOTS) await page.screenshot({ path: `../../../docs/screens/fix-65/staff-no-company-${viewport.width}.png`, fullPage: true });
			await expectNoAxeViolations(page);
		});
	});
}
