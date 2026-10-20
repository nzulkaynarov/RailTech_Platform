import { test, expect } from '@playwright/test';
import { mockSettingsApi } from './mocks/settingsApi';

/**
 * FIX-42 — Settings Hub против замоканного API (без стенда):
 *   • общие поля (имя, почта поддержки, логотип, домен) — только просмотр, «Изменить в CRM» ведёт в CRM;
 *   • сохранение шлёт только НДС;
 *   • категория с подкатегориями не удаляется, диалог называет подкатегории;
 *   • в «Дефолтах КП» нет неработающего переключателя уведомлений.
 * Скриншоты в docs/screens/fix-42/ — только при `SCREENSHOTS=1` (по умолчанию тест их не пишет).
 */
const SHOTS = process.env.SCREENSHOTS === '1';
const VIEWPORTS = [{ width: 1440, height: 900 }, { width: 390, height: 844 }];

for (const viewport of VIEWPORTS) {
	test.describe(`${viewport.width} px`, () => {
		test.use({ viewport });

		test('платформа: общие поля только для просмотра, ссылка в CRM, PATCH только с НДС', async ({ page }) => {
			const api = await mockSettingsApi(page);
			await page.goto('/?section=platform#settings');

			const link = page.getByRole('link', { name: 'Изменить в CRM' });
			await expect(link).toBeVisible({ timeout: 30_000 });
			await expect(link).toHaveAttribute('href', 'https://crm.example.test/settings');
			for (const value of ['RailTech ERP', 'support@example.test', 'https://cdn.example.test/logo.png', 'erp.example.test']) {
				await expect(page.locator(`input[value="${value}"]`)).toBeDisabled();
			}
			if (SHOTS) await page.screenshot({ path: `../../../docs/screens/fix-42/platform-${viewport.width}.png`, fullPage: true });

			await page.getByRole('button', { name: 'Сохранить' }).click();
			await expect.poll(() => api.systemSettingsPatches.length).toBe(1);
			expect(api.systemSettingsPatches[0]).toEqual({ vat_rate: '12.00' });
		});

		test('категории: с подкатегориями не удаляется, диалог их называет', async ({ page }) => {
			await mockSettingsApi(page);
			await page.goto('/?section=categories#settings');

			const row = page.getByRole('row', { name: /^Запчасти/ });
			await expect(row).toBeVisible({ timeout: 30_000 });
			await row.getByRole('button', { name: 'Удалить' }).click();
			const dialog = page.getByRole('alertdialog');
			await expect(dialog).toContainText('пока в ней есть подкатегории: Подшипники');
			await expect(dialog.getByRole('button', { name: 'Удалить' })).toBeDisabled();
			if (SHOTS) await page.screenshot({ path: `../../../docs/screens/fix-42/categories-delete-${viewport.width}.png` });
		});

		test('дефолты КП: переключателя уведомлений о сдвигах нет', async ({ page }) => {
			await mockSettingsApi(page);
			await page.goto('/?section=defaults#settings');

			await expect(page.getByText('Дефолты КП').first()).toBeVisible({ timeout: 30_000 });
			await expect(page.getByText('Максимальный возраст курса валюты (дней)')).toBeVisible();
			await expect(page.getByText('Уведомлять клиента о сдвигах сроков')).toHaveCount(0);
			await expect(page.getByRole('switch')).toHaveCount(0);
			if (SHOTS) await page.screenshot({ path: `../../../docs/screens/fix-42/defaults-${viewport.width}.png`, fullPage: true });
		});
	});
}
