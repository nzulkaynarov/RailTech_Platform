/**
 * ДС-1: срок договора в Cabinet — колонка «Срок» в списке договоров и отказ от продления с подтверждением (последний день
 * отказа назван в окне). Dev-сборка с моком портального API (MSW): `E2E_SCREENS_SPEC=ds1-contract-term` на конфиге
 * playwright.screens.config.ts. Снимки 1440 и 390 px и axe — в docs/screens/ds1 (E2E_SCREENS_DIR).
 */
import { expect, test, type Page } from '@playwright/test';
import { snap } from './helpers/shots';

const FIXTURE_NOW = new Date('2026-10-14T12:00:00+05:00');
const SIZES = [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
] as const;

async function signIn(page: Page) {
  await page.clock.setFixedTime(FIXTURE_NOW);
  await page.route('https://telegram.org/**', (route) => route.fulfill({ contentType: 'text/javascript', body: '' }));
  await page.addInitScript(
    ([session, lang]) => {
      window.sessionStorage.setItem('cabinet.mock.session', session);
      window.localStorage.setItem('cabinet.language', lang);
      window.localStorage.setItem('rt-cab-sidebar-collapsed-v1', 'false');
    },
    [JSON.stringify({ role: 'actor', auth_method: 'magic_link', dataset: 'demo' }), 'ru'] as const,
  );
}

for (const size of SIZES) {
  test(`договоры: срок и отказ от продления, ${String(size.width)}`, async ({ page }) => {
    await page.setViewportSize(size);
    await signIn(page);
    await page.goto('/contracts');
    await expect(page.getByRole('heading', { level: 1, name: 'Договоры' })).toBeVisible();
    await expect(page.getByText('до 31 дек. 2026 г. · продлится сам')).toBeVisible();
    await snap(page, 'cabinet-contract-term', { widths: [size] });

    await page.getByRole('button', { name: /Действия.*D-2026-0035|D-2026-0035/ }).first().click();
    await page.getByRole('menuitem', { name: 'Отказаться от продления' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText(/До 1 дек\. 2026 г\. можно отказаться/)).toBeVisible();
    await snap(page, 'cabinet-contract-decline', { widths: [size] });

    await dialog.getByRole('button', { name: 'Отказаться от продления' }).click();
    await expect(page.getByText('Вы отказались от продления договора D-2026-0035.')).toBeVisible();
    await expect(page.getByText('до 31 дек. 2026 г. · закончится в срок')).toBeVisible();
  });
}
